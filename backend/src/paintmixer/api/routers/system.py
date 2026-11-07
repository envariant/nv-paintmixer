"""Health and application settings."""

from __future__ import annotations

from fastapi import APIRouter
from sqlmodel import col, select

from paintmixer import __version__
from paintmixer.api.deps import SessionDep
from paintmixer.api.schemas import AppSettings, AppSettingsUpdate, Health
from paintmixer.api.services import load_settings, save_settings
from paintmixer.db import models as m

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Health)
def health(session: SessionDep) -> Health:
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    return Health(status="ok", version=__version__, active_model_version=fm.version if fm else None)


@router.get("/settings", response_model=AppSettings)
def get_settings(session: SessionDep) -> AppSettings:
    return load_settings(session)


@router.patch("/settings", response_model=AppSettings)
def update_settings(body: AppSettingsUpdate, session: SessionDep) -> AppSettings:
    cur = load_settings(session).model_dump()
    cur.update(body.model_dump(exclude_unset=True, exclude_none=True))
    return save_settings(session, AppSettings.model_validate(cur))
