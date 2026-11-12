"""Machine status (the top-bar pill and its popover), shared by GET /machine and the event
stream."""

from __future__ import annotations

from sqlmodel import Session, col, select

from paintmixer.api.schemas import JobBrief, MachineStatus
from paintmixer.api.services import all_paints, load_settings
from paintmixer.colorsci.convert import lab_to_srgb, srgb_to_hex
from paintmixer.db import models as m

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


def job_brief(j: m.Job) -> JobBrief:
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
        running=j.running,
        updated_at=j.updated_at,
    )


def machine_snapshot(session: Session) -> MachineStatus:
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
        current_job=job_brief(cur) if cur else None,
        recent=[job_brief(j) for j in recent],
    )
