"""Machine status for the top-bar pill and its popover (running job + recent jobs)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlmodel import col, select

from paintmixer.api.deps import SessionDep
from paintmixer.api.schemas import JobBrief, MachineStatus
from paintmixer.api.services import all_paints, load_settings
from paintmixer.colorsci.convert import lab_to_srgb, srgb_to_hex
from paintmixer.db import models as m

router = APIRouter(tags=["machine"])

RUNNING = (
    "queued",
    "pouring",
    "measuring",
    "dispensed",
    "measured",
    "correcting",
    "needs_attention",
)
FINISHED = ("done", "accepted", "cancelled")
_STATE = {
    "queued": "pouring",
    "pouring": "pouring",
    "measuring": "measuring",
    "dispensed": "measuring",
    "measured": "correcting",
    "correcting": "correcting",
    "needs_attention": "attention",
}


def _hex(lab: list[float] | None) -> str | None:
    return None if not lab else srgb_to_hex(lab_to_srgb(lab).rgb)


def brief(j: m.Job) -> JobBrief:
    meas = j.measured or {}
    last_lab = meas.get("lab") or j.recipe.get("predicted_lab")
    return JobBrief(
        id=j.id or 0,
        name=j.name,
        status=j.status,
        target_hex=_hex(j.target.get("lab")),
        last_hex=meas.get("hex") or _hex(last_lab),
        last_de=meas.get("de_to_target"),
        round=int(j.recipe.get("iteration", 0)),
        batch_volume_ml=j.batch_volume_ml,
        poured_ml=sum((j.dispensed or {}).get("cup_ml", {}).values()),
        step=j.step,
        progress=j.progress,
        paused=j.paused,
        updated_at=j.updated_at,
    )


@router.get("/machine", response_model=MachineStatus)
def machine_status(session: SessionDep) -> MachineStatus:
    s = load_settings(session)
    loaded = sum(1 for p in all_paints(session) if p.loaded)
    cur = session.exec(
        select(m.Job).where(col(m.Job.status).in_(RUNNING)).order_by(col(m.Job.updated_at).desc())
    ).first()
    recent = session.exec(
        select(m.Job)
        .where(col(m.Job.status).in_(FINISHED))
        .order_by(col(m.Job.updated_at).desc())
        .limit(5)
    ).all()
    state = _STATE.get(cur.status, "ready") if cur else "ready"
    label = "Machine ready" if cur is None else f"{state.capitalize()} · {cur.name}"
    if cur is not None and cur.paused:
        label = f"Paused · {cur.name}"
    transport = s.dispenser_transport
    return MachineStatus(
        name="DSP-01 (simulated)"
        if transport == "none"
        else f"Dispenser ({transport} {s.dispenser_address})",
        transport=transport,
        channels=s.dispenser_channels,
        channels_loaded=loaded,
        state=state,
        label=label,
        current_job=brief(cur) if cur else None,
        recent=[brief(j) for j in recent],
    )
