"""Machine status for the top-bar pill and its popover (running job + recent jobs)."""

from __future__ import annotations

from fastapi import APIRouter

from paintmixer.api.deps import SessionDep
from paintmixer.api.machine_state import machine_snapshot
from paintmixer.api.schemas import MachineStatus

router = APIRouter(tags=["machine"])


@router.get("/machine", response_model=MachineStatus)
def machine_status(session: SessionDep) -> MachineStatus:
    return machine_snapshot(session)
