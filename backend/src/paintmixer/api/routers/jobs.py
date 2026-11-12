"""Mixing jobs: create from a recipe, run it on the machine, measure, correct, accept.

Job status flow: ``draft`` -> ``queued`` -> ``pouring`` -> ``measuring`` (simulated runs) or
``dispensed`` (waiting for ``POST /measurement``) -> ``measured`` -> ``done`` within tolerance,
or ``correcting`` -> pour again ... -> ``needs_attention`` at the iteration cap. ``dispense``
runs in the background (:mod:`paintmixer.api.runner`); ``pause`` / ``resume`` / ``cancel`` act
between channels. ``accept`` ends a job the person is happy with (``accepted``); ``cancel``
abandons it (``cancelled``) and records what was already poured.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import numpy as np
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlmodel import Session, col, select

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, ApiError, bad_request, not_found
from paintmixer.api.jobs_core import (
    apply_correction,
    apply_measurement,
    poured_ml,
    save,
    simulated_reading,
)
from paintmixer.api.runner import MachineRunner, RunOptions
from paintmixer.api.schemas import (
    CancelRequest,
    CorrectRequest,
    DispenseRequest,
    JobCreate,
    JobRead,
    MeasurementIn,
)
from paintmixer.api.services import load_settings, pool_model, resolve_target
from paintmixer.colorsci.convert import reflectance_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.db import models as m
from paintmixer.db.models import utcnow

router = APIRouter(prefix="/jobs", tags=["jobs"], responses=ERROR_RESPONSES)


def _get(session: Session, job_id: int) -> m.Job:
    j = session.get(m.Job, job_id)
    if j is None:
        raise not_found("job", job_id)
    return j


@router.post("", response_model=JobRead, status_code=201)
def create_job(body: JobCreate, session: SessionDep) -> JobRead:
    s = load_settings(session)
    model, fm = pool_model(session, list(body.components))
    if any(v < 0 for v in body.components.values()) or sum(body.components.values()) <= 0:
        raise bad_request("bad_components", "fractions must be >= 0 with a positive sum")
    target = resolve_target(session, body.target)
    ids = list(body.components)
    c = np.array([body.components[p] for p in ids])
    c = c / c.sum()
    batch = body.batch_volume_ml or s.batch_volume_ml
    if batch > s.machine_max_batch_ml:
        raise bad_request(
            "batch_too_large",
            f"batch_volume_ml exceeds the machine maximum ({s.machine_max_batch_ml:g} ml)",
        )
    res = s.dispenser_resolution_ml
    vols = np.maximum(np.round(c * batch / res) * res, res)
    idx = np.arange(len(ids))[None, :]
    lab = model.lab(idx, c[None, :])[0]
    j = m.Job(
        name=body.name or (target.name or "Job"),
        status="draft",
        target={
            "lab": [float(x) for x in target.lab],
            "name": target.name,
            "spectrum": None if target.spectrum is None else [float(x) for x in target.spectrum],
        },
        constraints=body.constraints,
        recipe={
            "paint_ids": ids,
            "fractions": c.tolist(),
            "volumes_ml": vols.tolist(),
            "predicted_lab": lab.tolist(),
            "predicted_de": float(delta_e_2000(lab, target.lab)),
            "iteration": 0,
        },
        batch_volume_ml=batch,
        model_version=fm.version,
    )
    return save(session, j)


@router.get("", response_model=list[JobRead])
def list_jobs(session: SessionDep, status: str | None = Query(None)) -> list[JobRead]:
    q = select(m.Job).order_by(col(m.Job.id).desc())
    if status is not None:
        q = q.where(m.Job.status == status)
    return [JobRead.model_validate(j.model_dump()) for j in session.exec(q).all()]


EXPORT_COLUMNS = (
    "id",
    "name",
    "created",
    "status",
    "rounds",
    "final_de",
    "poured_ml",
    "paints",
)


def _cell(text: str) -> str:
    """Text cells that a spreadsheet would read as a formula get a leading apostrophe."""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _iso_utc(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def export_rows(session: Session, jobs: list[m.Job]) -> list[dict[str, str]]:
    """One row per job for the machine log: rounds measured, the last measured dE2000 to the
    target (blank before any measurement), the volume in the cup and the paints by name."""
    names = {p.id: p.name for p in session.exec(select(m.Paint)).all()}
    rows = []
    for j in jobs:
        de = (j.measured or {}).get("de_to_target")
        rows.append(
            {
                "id": str(j.id),
                "name": _cell(j.name),
                "created": _iso_utc(j.created_at),
                "status": j.status,
                "rounds": str(sum(1 for c in j.corrections if c.get("kind") == "round")),
                "final_de": "" if de is None else f"{de:.2f}",
                "poured_ml": f"{poured_ml(j):.1f}",
                "paints": _cell("; ".join(names.get(p, p) for p in j.recipe.get("paint_ids", []))),
            }
        )
    return rows


@router.get(
    "/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Job log as CSV"}},
)
def export_jobs(session: SessionDep, status: str | None = Query(None)) -> Response:
    """The job log as CSV (Export log in the machine popover), newest first. Columns: id,
    name, created (ISO 8601, UTC), status, rounds, final_de, poured_ml, paints."""
    q = select(m.Job).order_by(col(m.Job.id).desc())
    if status is not None:
        q = q.where(m.Job.status == status)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(export_rows(session, list(session.exec(q).all())))
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="paintmixer-jobs.csv"'},
    )


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, session: SessionDep) -> JobRead:
    return JobRead.model_validate(_get(session, job_id).model_dump())


@router.post("/{job_id}/dispense", response_model=JobRead, status_code=202)
def dispense(job_id: int, body: DispenseRequest, session: SessionDep, request: Request) -> JobRead:
    """Run the job on the machine in the background (the recipe, or the pending correction
    additions). Returns at once with status ``queued``; poll ``GET /jobs/{id}``."""
    j = _get(session, job_id)
    if j.status not in ("draft", "correcting"):
        raise ApiError(409, "bad_state", f"cannot dispense a job in status {j.status!r}")
    if not body.simulate and load_settings(session).dispenser_transport == "none":
        raise bad_request(
            "no_dispenser",
            "no dispenser is configured (settings.dispenser_transport); use simulate=true",
        )
    if j.running:
        raise ApiError(409, "bad_state", "the job is already on the machine")
    j.status, j.step, j.progress, j.paused, j.running = "queued", "Queued", 0.0, False, True
    out = save(session, j)
    _runner(request).submit(
        job_id,
        RunOptions(
            simulate=body.simulate,
            seed=body.seed,
            rel_sigma=body.rel_sigma,
            abs_sigma_ml=body.abs_sigma_ml,
            measure=body.measure,
            auto_correct_rounds=body.auto_correct_rounds,
            ml_per_s=body.simulate_ml_per_s,
            gain=body.simulate_gain,
        ),
    )
    return out


@router.post("/{job_id}/pause", response_model=JobRead)
def pause(job_id: int, session: SessionDep, request: Request) -> JobRead:
    """Pause a queued or running job before its next channel."""
    j = _get(session, job_id)
    if not _runner(request).pause(job_id):
        raise ApiError(409, "bad_state", f"job is not on the machine (status is {j.status!r})")
    j.paused = True
    return save(session, j)


@router.post("/{job_id}/resume", response_model=JobRead)
def resume(job_id: int, session: SessionDep, request: Request) -> JobRead:
    j = _get(session, job_id)
    if not _runner(request).resume(job_id):
        raise ApiError(409, "bad_state", f"job is not on the machine (status is {j.status!r})")
    j.paused = False
    return save(session, j)


@router.post("/{job_id}/measurement", response_model=JobRead)
def record_measurement(job_id: int, body: MeasurementIn, session: SessionDep) -> JobRead:
    """Record the measured colour of the mix (spectrum, Lab, or a simulated reading)."""
    j = _get(session, job_id)
    if j.status != "dispensed":
        raise ApiError(409, "bad_state", f"measure after dispensing (status is {j.status!r})")
    spectrum = None
    if body.simulate:
        spectrum = simulated_reading(
            session,
            j,
            noise=body.simulate_noise,
            gain=body.simulate_gain,
            offset=body.simulate_offset,
            seed=body.seed,
        )
        lab = reflectance_to_lab(spectrum)
    elif body.spectrum is not None:
        spectrum = np.array(body.spectrum)
        lab = reflectance_to_lab(spectrum)
    else:
        lab = np.array(body.lab)
    apply_measurement(session, j, lab, spectrum, simulated=body.simulate)
    j.step, j.progress = "Measured", 1.0
    return save(session, j)


@router.post("/{job_id}/correct", response_model=JobRead)
def correct(job_id: int, body: CorrectRequest, session: SessionDep) -> JobRead:
    """One damped Gauss-Newton correction from the latest measurement ("Correct again";
    then ``dispense`` pours it)."""
    j = _get(session, job_id)
    if j.status != "measured" or j.measured is None:
        raise ApiError(409, "bad_state", f"correct after a measurement (status is {j.status!r})")
    s = load_settings(session)
    apply_correction(
        session,
        j,
        tolerance=body.tolerance_de if body.tolerance_de is not None else s.accept_tolerance_de,
        max_iterations=body.max_iterations,
        mode=body.mode,
        damping=body.damping,
        resolution_ml=s.dispenser_resolution_ml,
    )
    return save(session, j)


OPEN_STATES = (
    "draft",
    "queued",
    "pouring",
    "dispensed",
    "measuring",
    "measured",
    "correcting",
    "needs_attention",
)


@router.post("/{job_id}/accept", response_model=JobRead)
def accept(job_id: int, session: SessionDep) -> JobRead:
    """Accept the mix as it is (after a measurement), whatever its dE."""
    j = _get(session, job_id)
    if j.status not in ("measured", "needs_attention", "done") or j.measured is None:
        raise ApiError(409, "bad_state", f"accept after a measurement (status is {j.status!r})")
    j.corrections = [
        *j.corrections,
        {
            "iteration": j.recipe.get("iteration", 0),
            "result": "accepted",
            "measured_de": j.measured.get("de_to_target"),
            "at": utcnow().isoformat(),
        },
    ]
    j.status, j.step = "accepted", "Accepted"
    return save(session, j)


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel(job_id: int, body: CancelRequest, session: SessionDep, request: Request) -> JobRead:
    """Abandon a job. A queued job is cancelled at once; a running one stops before its next
    channel (poll for ``cancelled``). What is already in the cup stays there and is logged."""
    j = _get(session, job_id)
    if j.status not in OPEN_STATES:
        raise ApiError(409, "bad_state", f"cannot cancel a job in status {j.status!r}")
    if _runner(request).cancel(job_id, body.reason):
        session.refresh(j)
        if j.status != "cancelled":
            j.step = "Cancelling"
            return save(session, j)
        return JobRead.model_validate(j.model_dump())
    j.corrections = [
        *j.corrections,
        {
            "iteration": j.recipe.get("iteration", 0),
            "result": "cancelled",
            "poured_ml": poured_ml(j),
            "reason": body.reason,
            "at": utcnow().isoformat(),
        },
    ]
    j.status, j.step, j.paused = "cancelled", "Cancelled", False
    return save(session, j)


def _runner(request: Request) -> MachineRunner:
    runner: MachineRunner = request.app.state.runner
    return runner
