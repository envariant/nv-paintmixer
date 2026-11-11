"""Mixing jobs: create from a recipe, (simulated) dispense, record a measurement, correct.

Job status flow: ``draft`` -> ``dispensed`` -> ``measured`` -> (``correcting`` -> dispense ...)
-> ``done`` (within tolerance) or ``needs_attention`` (iteration cap reached).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Query
from sqlmodel import Session, col, select

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, ApiError, bad_request, not_found
from paintmixer.api.schemas import (
    CorrectRequest,
    DispenseRequest,
    JobCreate,
    JobRead,
    MeasurementIn,
)
from paintmixer.api.services import (
    all_paints,
    km_of,
    load_settings,
    pool_model,
    resolve_target,
)
from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.correction import additions_for, correction_step
from paintmixer.db import models as m
from paintmixer.db.models import utcnow
from paintmixer.hardware.dispenser import DispenserError, SimulatedDispenser, dispense_recipe
from paintmixer.measurement.base import MeasureRequest
from paintmixer.measurement.sources import SimulatedSource

router = APIRouter(prefix="/jobs", tags=["jobs"], responses=ERROR_RESPONSES)


def _get(session: Session, job_id: int) -> m.Job:
    j = session.get(m.Job, job_id)
    if j is None:
        raise not_found("job", job_id)
    return j


def _save(session: Session, j: m.Job) -> JobRead:
    j.updated_at = utcnow()
    # JSON columns are replaced (not mutated) so SQLAlchemy sees the change
    session.add(j)
    session.commit()
    session.refresh(j)
    return JobRead.model_validate(j.model_dump())


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
    return _save(session, j)


@router.get("", response_model=list[JobRead])
def list_jobs(session: SessionDep, status: str | None = Query(None)) -> list[JobRead]:
    q = select(m.Job).order_by(col(m.Job.id).desc())
    if status is not None:
        q = q.where(m.Job.status == status)
    return [JobRead.model_validate(j.model_dump()) for j in session.exec(q).all()]


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, session: SessionDep) -> JobRead:
    return JobRead.model_validate(_get(session, job_id).model_dump())


def _to_dispense(j: m.Job) -> dict[str, float]:
    """What still has to go into the cup: the batch, or the pending additions."""
    pending = j.recipe.get("pending_additions_ml")
    if pending is not None:
        return dict(zip(j.recipe["paint_ids"], pending, strict=True))
    return dict(zip(j.recipe["paint_ids"], j.recipe["volumes_ml"], strict=True))


@router.post("/{job_id}/dispense", response_model=JobRead)
def dispense(job_id: int, body: DispenseRequest, session: SessionDep) -> JobRead:
    """Dispense the recipe (or pending correction additions) with the simulated dispenser."""
    j = _get(session, job_id)
    if j.status not in ("draft", "correcting"):
        raise ApiError(409, "bad_state", f"cannot dispense a job in status {j.status!r}")
    if not body.simulate:
        raise bad_request("no_dispenser", "no hardware dispenser is configured; use simulate=true")
    paints = {p.id: p for p in all_paints(session)}
    channels = {
        p: (paints[p].dispenser_channel or i + 1) for i, p in enumerate(j.recipe["paint_ids"])
    }
    seed = body.seed if body.seed is not None else (j.id or 0) * 100 + len(j.corrections)
    disp = SimulatedDispenser(
        resolution_ml=load_settings(session).dispenser_resolution_ml,
        rel_sigma=body.rel_sigma,
        abs_sigma_ml=body.abs_sigma_ml,
        seed=seed,
    )
    try:
        results = dispense_recipe(disp, _to_dispense(j), channels)
    except DispenserError as e:
        raise bad_request("dispense_failed", str(e)) from e
    prev = (j.dispensed or {}).get("cup_ml", {p: 0.0 for p in j.recipe["paint_ids"]})
    cup = {p: prev.get(p, 0.0) for p in j.recipe["paint_ids"]}
    if j.recipe.get("mode") == "remix":
        cup = {p: 0.0 for p in cup}
    for r in results:
        cup[r.paint_id] += r.actual_ml
    events = [*(j.dispensed or {}).get("events", [])]
    events.append(
        {
            "iteration": j.recipe.get("iteration", 0),
            "results": [r.__dict__ for r in results],
            "at": utcnow().isoformat(),
        }
    )
    j.dispensed = {"cup_ml": cup, "events": events, "dispenser": disp.name}
    recipe = dict(j.recipe)
    recipe.pop("pending_additions_ml", None)
    j.recipe = recipe
    j.status = "dispensed"
    return _save(session, j)


@router.post("/{job_id}/measurement", response_model=JobRead)
def record_measurement(job_id: int, body: MeasurementIn, session: SessionDep) -> JobRead:
    """Record the measured colour of the mix (spectrum, Lab, or a simulated reading)."""
    j = _get(session, job_id)
    if j.status != "dispensed":
        raise ApiError(409, "bad_state", f"measure after dispensing (status is {j.status!r})")
    target = np.array(j.target["lab"])
    spectrum = None
    if body.simulate:
        fm = session.exec(
            select(m.FittedModel).where(m.FittedModel.version == j.model_version)
        ).one()
        cup = j.dispensed["cup_ml"] if j.dispensed else {}
        src = SimulatedSource(
            km_of(fm),
            fm.paint_ids,
            noise=body.simulate_noise,
            gain=body.simulate_gain,
            offset=body.simulate_offset,
            seed=body.seed if body.seed is not None else (j.id or 0) * 1000 + len(j.corrections),
        )
        spectrum = src.read(
            MeasureRequest(f"job-{j.id}", None, {k: v for k, v in cup.items() if v > 0})
        ).reflectance
        lab = reflectance_to_lab(spectrum)
    elif body.spectrum is not None:
        spectrum = np.array(body.spectrum)
        lab = reflectance_to_lab(spectrum)
    else:
        lab = np.array(body.lab)
    de = float(delta_e_2000(lab, target))
    pred = np.array(j.recipe["predicted_lab"])
    measured: dict[str, Any] = {
        "lab": lab.tolist(),
        "spectrum": None if spectrum is None else spectrum.round(6).tolist(),
        "hex": srgb_to_hex(reflectance_to_srgb(spectrum).rgb) if spectrum is not None else None,
        "de_to_target": de,
        "de_to_prediction": float(delta_e_2000(lab, pred)),
        "simulated": body.simulate,
        "iteration": j.recipe.get("iteration", 0),
        "at": utcnow().isoformat(),
    }
    j.measured = measured
    j.status = "measured"
    cup = (j.dispensed or {}).get("cup_ml", {})
    tot = sum(cup.values()) or 1.0
    session.add(
        m.CorrectionLog(
            job_id=j.id,
            iteration=j.recipe.get("iteration", 0),
            model_version=j.model_version,
            fractions={k: v / tot for k, v in cup.items()},
            predicted_lab=list(map(float, pred)),
            measured_lab=lab.tolist(),
            measured_spectrum=measured["spectrum"],
            target_lab=list(map(float, target)),
        )
    )
    return _save(session, j)


@router.post("/{job_id}/correct", response_model=JobRead)
def correct(job_id: int, body: CorrectRequest, session: SessionDep) -> JobRead:
    """One damped Gauss-Newton correction from the latest measurement."""
    j = _get(session, job_id)
    if j.status != "measured" or j.measured is None:
        raise ApiError(409, "bad_state", f"correct after a measurement (status is {j.status!r})")
    target = np.array(j.target["lab"])
    meas = np.array(j.measured["lab"])
    de = float(delta_e_2000(meas, target))
    iteration = int(j.recipe.get("iteration", 0))
    entry: dict[str, Any] = {
        "iteration": iteration,
        "measured_de": de,
        "measured_lab": meas.tolist(),
    }
    if de <= body.tolerance_de:
        entry["result"] = "within tolerance"
        j.corrections = [*j.corrections, entry]
        j.status = "done"
        return _save(session, j)
    if iteration >= body.max_iterations:
        entry["result"] = f"iteration cap ({body.max_iterations}) reached"
        j.corrections = [*j.corrections, entry]
        j.status = "needs_attention"
        return _save(session, j)
    ids = j.recipe["paint_ids"]
    model, _ = pool_model(session, ids)
    cup = np.array([(j.dispensed or {}).get("cup_ml", {}).get(p, 0.0) for p in ids])
    actual = cup / cup.sum() if cup.sum() > 0 else np.array(j.recipe["fractions"])
    idx = np.arange(len(ids))
    step = correction_step(model, idx, actual, target, meas, damping=body.damping)
    recipe = dict(j.recipe)
    recipe.update(
        fractions=step.fractions.tolist(),
        predicted_lab=step.predicted_lab.tolist(),
        predicted_de=step.expected_de,
        iteration=iteration + 1,
        mode=body.mode,
    )
    res = load_settings(session).dispenser_resolution_ml
    if body.mode == "additions":
        adds, total = additions_for(cup, step.fractions)
        adds = np.round(adds / res) * res
        recipe["pending_additions_ml"] = adds.tolist()
        entry.update(additions_ml=dict(zip(ids, adds.tolist(), strict=True)), new_total_ml=total)
    else:
        vols = np.maximum(np.round(step.fractions * j.batch_volume_ml / res) * res, res)
        recipe["volumes_ml"] = vols.tolist()
    entry.update(
        result="corrected",
        new_fractions=dict(zip(ids, step.fractions.tolist(), strict=True)),
        expected_de=step.expected_de,
        mode=body.mode,
    )
    j.recipe = recipe
    j.corrections = [*j.corrections, entry]
    j.status = "correcting"
    return _save(session, j)
