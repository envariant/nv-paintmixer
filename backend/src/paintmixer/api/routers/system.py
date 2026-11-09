"""Health and application settings."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import ValidationError
from sqlmodel import col, select

from paintmixer import __version__
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import bad_request
from paintmixer.api.schemas import AppSettings, AppSettingsUpdate, Colorimetry, Health
from paintmixer.api.services import load_settings, save_settings
from paintmixer.db import models as m
from paintmixer.parity import colorimetry

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Health)
def health(session: SessionDep) -> Health:
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    return Health(
        status="ok",
        version=__version__,
        active_model_version=fm.version if fm else None,
        active_model_source=fm.source if fm else None,
    )


@router.get("/colorimetry", response_model=Colorimetry)
def get_colorimetry() -> Colorimetry:
    """Weighting tables (D65, A, F11; CIE 1931 2°) and sRGB constants exactly as the backend uses
    them, so clients can run the forward model locally (see ``GET /models/{v}/spectra``)."""
    return Colorimetry.model_validate(colorimetry())


@router.get("/settings", response_model=AppSettings)
def get_settings(session: SessionDep) -> AppSettings:
    return load_settings(session)


@router.patch("/settings", response_model=AppSettings)
def update_settings(body: AppSettingsUpdate, session: SessionDep) -> AppSettings:
    cur = load_settings(session).model_dump()
    cur.update(body.model_dump(exclude_unset=True, exclude_none=True))
    try:
        new = AppSettings.model_validate(cur)
    except ValidationError as e:
        raise bad_request(
            "invalid_settings",
            "; ".join(err["msg"] for err in e.errors()),
            [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()],
        ) from e
    return save_settings(session, new)
