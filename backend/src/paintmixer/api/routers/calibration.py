"""Calibration data: validate/upload CSV, list samples, run fits in the background."""

from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, BackgroundTasks, File, Query, Request, Response, UploadFile
from sqlmodel import Session, col, delete, select

from paintmixer.api.compute import submit_background
from paintmixer.api.deps import ConfigDep, SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, not_found
from paintmixer.api.importers import create_fit_run, report_out, run_fit, store_calibration
from paintmixer.api.schemas import (
    FitRequest,
    FitRunRead,
    SampleRead,
    UploadResult,
    ValidationReportOut,
)
from paintmixer.api.services import (
    paint_infos,
)
from paintmixer.calibration.format import parse_calibration_csv
from paintmixer.colorsci.convert import reflectance_to_srgb, srgb_to_hex
from paintmixer.db import models as m

router = APIRouter(prefix="/calibration", tags=["calibration"], responses=ERROR_RESPONSES)


async def _read_csv(file: UploadFile) -> str:
    raw = await file.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise bad_request("bad_encoding", "calibration files must be UTF-8 CSV") from e


@router.post("/validate", response_model=ValidationReportOut)
async def validate(session: SessionDep, file: UploadFile = File(...)) -> ValidationReportOut:
    """Validate a calibration CSV against the paint library without storing it."""
    return report_out(parse_calibration_csv(await _read_csv(file), paint_infos(session)))


@router.post("/upload", response_model=UploadResult)
async def upload(
    session: SessionDep,
    file: UploadFile = File(...),
    mode: Literal["append", "replace"] = Query(
        "append", description="append: upsert by sample_id; replace: delete all samples first"
    ),
    allow_partial: bool = Query(False, description="store valid rows even if some rows fail"),
) -> UploadResult:
    text = await _read_csv(file)
    return store_calibration(session, text, file.filename or "upload.csv", mode, allow_partial)


def _sample_out(s: m.CalibrationSample) -> SampleRead:
    rgb = reflectance_to_srgb(np.array(s.reflectance)).rgb
    return SampleRead.model_validate({**s.model_dump(), "hex": srgb_to_hex(rgb)})


@router.get("/samples", response_model=list[SampleRead])
def list_samples(
    session: SessionDep,
    type: str | None = None,
    paint_id: str | None = Query(None, description="Only samples containing this paint"),
    holdout: bool | None = None,
) -> list[SampleRead]:
    q = select(m.CalibrationSample).order_by(
        col(m.CalibrationSample.created_at), col(m.CalibrationSample.id)
    )
    if type is not None:
        q = q.where(m.CalibrationSample.type == type)
    if holdout is not None:
        q = q.where(m.CalibrationSample.holdout == holdout)
    rows = session.exec(q).all()
    if paint_id is not None:
        rows = [r for r in rows if paint_id in r.components]
    return [_sample_out(r) for r in rows]


@router.get("/samples/{sample_id}", response_model=SampleRead)
def get_sample(sample_id: str, session: SessionDep) -> SampleRead:
    s = session.get(m.CalibrationSample, sample_id)
    if s is None:
        raise not_found("sample", sample_id)
    return _sample_out(s)


@router.delete("/samples/{sample_id}", status_code=204)
def delete_sample(sample_id: str, session: SessionDep) -> Response:
    s = session.get(m.CalibrationSample, sample_id)
    if s is None:
        raise not_found("sample", sample_id)
    session.delete(s)
    session.commit()
    return Response(status_code=204)


@router.delete("/samples", status_code=204)
def delete_all_samples(session: SessionDep) -> Response:
    session.exec(delete(m.CalibrationSample))
    session.commit()
    return Response(status_code=204)


# --- fitting --------------------------------------------------------------------------------


def _run_out(session: Session, r: m.FitRun) -> FitRunRead:
    version = None
    if r.model_id is not None:
        fm = session.get(m.FittedModel, r.model_id)
        version = fm.version if fm else None
    return FitRunRead.model_validate({**r.model_dump(), "model_version": version})


@router.post("/fit", response_model=FitRunRead, status_code=202)
def start_fit(
    body: FitRequest,
    session: SessionDep,
    config: ConfigDep,
    background: BackgroundTasks,
    request: Request,
) -> FitRunRead:
    """Start a fit in the background; poll ``GET /calibration/fits/{id}``."""
    run = create_fit_run(session, body)
    assert run.id is not None
    if submit_background(request.app, run_fit, config.database_url, run.id) is None:
        background.add_task(run_fit, config.database_url, run.id)
    return _run_out(session, run)


@router.get("/fits", response_model=list[FitRunRead])
def list_fits(session: SessionDep, limit: int = Query(20, ge=1, le=200)) -> list[FitRunRead]:
    runs = session.exec(select(m.FitRun).order_by(col(m.FitRun.id).desc()).limit(limit)).all()
    return [_run_out(session, r) for r in runs]


@router.get("/fits/{run_id}", response_model=FitRunRead)
def get_fit(run_id: int, session: SessionDep) -> FitRunRead:
    r = session.get(m.FitRun, run_id)
    if r is None:
        raise not_found("fit run", run_id)
    return _run_out(session, r)
