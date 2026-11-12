"""Job steps shared by the job endpoints and the machine runner (:mod:`paintmixer.api.runner`).

None of these commit; the caller saves the job (:func:`save`).

``corrections`` is the job's log. Besides the correction / accept / cancel entries (``result``),
every measurement adds a *round* entry (``kind: "round"``) with what the run screen's trail
shows: ``label`` ("First pour", "Fix 1", ...), the measured colour ``hex``, its ``de`` to the
target, the ``added_ml`` poured in that round and the ``poured_ml`` in the cup.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlmodel import Session, select

from paintmixer.api.schemas import JobRead
from paintmixer.api.services import all_paints, km_of, pool_model
from paintmixer.colorsci.convert import lab_to_srgb, srgb_to_hex
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.types import FloatArray
from paintmixer.correction import additions_for, correction_step
from paintmixer.db import models as m
from paintmixer.db.models import utcnow
from paintmixer.hardware.dispenser import DispenseResult
from paintmixer.measurement.base import MeasureRequest
from paintmixer.measurement.sources import SimulatedSource


def save(session: Session, j: m.Job) -> JobRead:
    j.updated_at = utcnow()
    # JSON columns are replaced (not mutated) so SQLAlchemy sees the change
    session.add(j)
    session.commit()
    session.refresh(j)
    return JobRead.model_validate(j.model_dump())


def round_label(iteration: int) -> str:
    return "First pour" if iteration == 0 else f"Fix {iteration}"


def to_dispense(j: m.Job) -> dict[str, float]:
    """What still has to go into the cup: the batch, or the pending additions."""
    pending = j.recipe.get("pending_additions_ml")
    if pending is not None:
        return dict(zip(j.recipe["paint_ids"], pending, strict=True))
    return dict(zip(j.recipe["paint_ids"], j.recipe["volumes_ml"], strict=True))


def channels_for(session: Session, j: m.Job) -> dict[str, int]:
    loaded = {p.id: p.dispenser_channel for p in all_paints(session) if p.dispenser_channel}
    return {p: loaded.get(p) or i + 1 for i, p in enumerate(j.recipe["paint_ids"])}


def poured_ml(j: m.Job) -> float:
    return float(sum((j.dispensed or {}).get("cup_ml", {}).values()))


def apply_pour(
    session: Session, j: m.Job, results: list[DispenseResult], dispenser_name: str
) -> None:
    """Add what was poured to the cup and the paints' levels; the job becomes ``dispensed``."""
    paints = {p.id: p for p in all_paints(session)}
    prev = (j.dispensed or {}).get("cup_ml", {p: 0.0 for p in j.recipe["paint_ids"]})
    cup = {p: prev.get(p, 0.0) for p in j.recipe["paint_ids"]}
    if j.recipe.get("mode") == "remix":
        cup = {p: 0.0 for p in cup}
    for r in results:
        cup[r.paint_id] += r.actual_ml
        p = paints.get(r.paint_id)
        if p is not None and p.level_ml is not None:  # track the reservoir
            p.level_ml = max(0.0, p.level_ml - r.actual_ml)
            p.updated_at = utcnow()
            session.add(p)
    events = [*(j.dispensed or {}).get("events", [])]
    events.append(
        {
            "iteration": j.recipe.get("iteration", 0),
            "results": [r.__dict__ for r in results],
            "at": utcnow().isoformat(),
        }
    )
    j.dispensed = {"cup_ml": cup, "events": events, "dispenser": dispenser_name}
    recipe = dict(j.recipe)
    recipe.pop("pending_additions_ml", None)
    j.recipe = recipe
    j.status = "dispensed"


def simulated_reading(
    session: Session,
    j: m.Job,
    *,
    noise: float = 0.001,
    gain: float = 1.0,
    offset: float = 0.0,
    seed: int | None = None,
) -> FloatArray:
    """The cup's spectrum as the simulated instrument reads it (the job's model + noise)."""
    fm = session.exec(select(m.FittedModel).where(m.FittedModel.version == j.model_version)).one()
    cup = j.dispensed["cup_ml"] if j.dispensed else {}
    src = SimulatedSource(
        km_of(fm),
        fm.paint_ids,
        noise=noise,
        gain=gain,
        offset=offset,
        seed=seed if seed is not None else (j.id or 0) * 1000 + len(j.corrections),
    )
    reading = src.read(MeasureRequest(f"job-{j.id}", None, {k: v for k, v in cup.items() if v > 0}))
    out: FloatArray = reading.reflectance
    return out


def apply_measurement(
    session: Session,
    j: m.Job,
    lab: FloatArray,
    spectrum: FloatArray | None,
    *,
    simulated: bool,
) -> float:
    """Record the cup's measured colour (and a round entry); the job becomes ``measured``.
    Returns the dE2000 to the target."""
    from paintmixer.colorsci.convert import reflectance_to_srgb

    target = np.array(j.target["lab"])
    de = float(delta_e_2000(lab, target))
    pred = np.array(j.recipe["predicted_lab"])
    iteration = int(j.recipe.get("iteration", 0))
    hex_ = (
        srgb_to_hex(reflectance_to_srgb(spectrum).rgb)
        if spectrum is not None
        else srgb_to_hex(lab_to_srgb(lab).rgb)
    )
    measured: dict[str, Any] = {
        "lab": lab.tolist(),
        "spectrum": None if spectrum is None else spectrum.round(6).tolist(),
        "hex": hex_ if spectrum is not None else None,
        "de_to_target": de,
        "de_to_prediction": float(delta_e_2000(lab, pred)),
        "simulated": simulated,
        "iteration": iteration,
        "at": utcnow().isoformat(),
    }
    j.measured = measured
    j.status = "measured"
    cup = (j.dispensed or {}).get("cup_ml", {})
    tot = sum(cup.values()) or 1.0
    added = sum(
        r["actual_ml"]
        for ev in (j.dispensed or {}).get("events", [])
        if ev.get("iteration") == iteration
        for r in ev["results"]
    )
    j.corrections = [
        *j.corrections,
        {
            "kind": "round",
            "iteration": iteration,
            "label": round_label(iteration),
            "hex": hex_,
            "de": round(de, 4),
            "added_ml": round(float(added), 3),
            "poured_ml": round(float(sum(cup.values())), 3),
            "at": utcnow().isoformat(),
        },
    ]
    session.add(
        m.CorrectionLog(
            job_id=j.id,
            iteration=iteration,
            model_version=j.model_version,
            fractions={k: v / tot for k, v in cup.items()},
            predicted_lab=list(map(float, pred)),
            measured_lab=lab.tolist(),
            measured_spectrum=measured["spectrum"],
            target_lab=list(map(float, target)),
        )
    )
    return de


def apply_correction(
    session: Session,
    j: m.Job,
    *,
    tolerance: float,
    max_iterations: int,
    mode: str = "additions",
    damping: float = 1e-3,
    resolution_ml: float = 0.05,
) -> None:
    """One damped Gauss-Newton correction from the latest measurement: ``done`` within
    tolerance, ``needs_attention`` at the iteration cap, else ``correcting`` with the next
    round's additions (or remix volumes) in the recipe."""
    assert j.measured is not None
    target = np.array(j.target["lab"])
    meas = np.array(j.measured["lab"])
    de = float(delta_e_2000(meas, target))
    iteration = int(j.recipe.get("iteration", 0))
    entry: dict[str, Any] = {
        "iteration": iteration,
        "measured_de": de,
        "measured_lab": meas.tolist(),
    }
    if de <= tolerance:
        entry["result"] = "within tolerance"
        j.corrections = [*j.corrections, entry]
        j.status = "done"
        return
    if iteration >= max_iterations:
        entry["result"] = f"iteration cap ({max_iterations}) reached"
        j.corrections = [*j.corrections, entry]
        j.status = "needs_attention"
        return
    ids = j.recipe["paint_ids"]
    model, _ = pool_model(session, ids)
    cup = np.array([(j.dispensed or {}).get("cup_ml", {}).get(p, 0.0) for p in ids])
    actual = cup / cup.sum() if cup.sum() > 0 else np.array(j.recipe["fractions"])
    idx = np.arange(len(ids))
    step = correction_step(model, idx, actual, target, meas, damping=damping)
    recipe = dict(j.recipe)
    recipe.update(
        fractions=step.fractions.tolist(),
        predicted_lab=step.predicted_lab.tolist(),
        predicted_de=step.expected_de,
        iteration=iteration + 1,
        mode=mode,
    )
    if mode == "additions":
        adds, total = additions_for(cup, step.fractions)
        adds = np.round(adds / resolution_ml) * resolution_ml
        recipe["pending_additions_ml"] = adds.tolist()
        entry.update(additions_ml=dict(zip(ids, adds.tolist(), strict=True)), new_total_ml=total)
    else:
        vols = np.maximum(
            np.round(step.fractions * j.batch_volume_ml / resolution_ml) * resolution_ml,
            resolution_ml,
        )
        recipe["volumes_ml"] = vols.tolist()
    entry.update(
        result="corrected",
        new_fractions=dict(zip(ids, step.fractions.tolist(), strict=True)),
        expected_de=step.expected_de,
        mode=mode,
    )
    j.recipe = recipe
    j.corrections = [*j.corrections, entry]
    j.status = "correcting"
