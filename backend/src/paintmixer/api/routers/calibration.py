"""Calibration data: validate/upload CSV, list samples, run fits in the background."""

from __future__ import annotations

import traceback
from typing import Literal

import numpy as np
from fastapi import APIRouter, BackgroundTasks, File, Query, Request, Response, UploadFile
from sqlmodel import Session, col, delete, select

from paintmixer.api.compute import submit_background
from paintmixer.api.deps import ConfigDep, SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, not_found
from paintmixer.api.schemas import (
    FitRequest,
    FitRunRead,
    SampleRead,
    UploadResult,
    ValidationIssueOut,
    ValidationReportOut,
)
from paintmixer.api.services import (
    clean_floats,
    data_to_sample,
    load_settings,
    paint_infos,
    sample_to_data,
)
from paintmixer.calibration.fit import FitError, FitOptions, fit_calibration
from paintmixer.calibration.format import ValidationReport, parse_calibration_csv
from paintmixer.calibration.report import fit_result_to_dict
from paintmixer.colorsci.convert import reflectance_to_srgb, srgb_to_hex
from paintmixer.db import models as m
from paintmixer.db.models import utcnow
from paintmixer.db.session import get_engine

router = APIRouter(prefix="/calibration", tags=["calibration"], responses=ERROR_RESPONSES)


def report_out(rep: ValidationReport) -> ValidationReportOut:
    return ValidationReportOut(
        ok=rep.ok,
        n_rows=rep.n_rows,
        n_valid=len(rep.samples),
        n_errors=len(rep.errors),
        n_warnings=len(rep.warnings),
        issues=[ValidationIssueOut.model_validate(i.__dict__) for i in rep.issues],
        wavelengths_in=rep.wavelengths_in,
    )


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
    rep = parse_calibration_csv(text, paint_infos(session))
    out = report_out(rep)
    if not rep.ok and not allow_partial:
        return UploadResult(report=out, upload_id=None, stored=0, replaced=0)
    if mode == "replace":
        session.exec(delete(m.CalibrationSample))
    up = m.CalibrationUpload(
        filename=file.filename or "upload.csv",
        n_samples=len(rep.samples),
        issues=[i.__dict__ for i in rep.issues[:500]],
    )
    session.add(up)
    session.flush()
    replaced = 0
    for d in rep.samples:
        existing = session.get(m.CalibrationSample, d.sample_id)
        if existing is not None:
            session.delete(existing)
            session.flush()
            replaced += 1
        session.add(data_to_sample(d, up.id))
    session.commit()
    return UploadResult(report=out, upload_id=up.id, stored=len(rep.samples), replaced=replaced)


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


def run_fit(db_url: str, run_id: int) -> None:
    """Background job: fit, store a new model version, update the run row."""
    engine = get_engine(db_url)

    def update(**kw: object) -> None:
        with Session(engine) as s:
            run = s.get(m.FitRun, run_id)
            assert run is not None
            for k, v in kw.items():
                setattr(run, k, v)
            s.add(run)
            s.commit()

    update(status="running", started_at=utcnow(), message="loading samples", progress=0.01)
    try:
        with Session(engine) as s:
            run = s.get(m.FitRun, run_id)
            assert run is not None
            req = FitRequest.model_validate(run.options)
            settings = load_settings(s)
            paints = paint_infos(s)
            samples = [sample_to_data(x) for x in s.exec(select(m.CalibrationSample)).all()]
        opts = FitOptions(
            k1=req.k1 if req.k1 is not None else settings.saunderson_k1,
            k2=req.k2 if req.k2 is not None else settings.saunderson_k2,
            smoothness=req.smoothness,
            k_folds=req.k_folds,
        )
        result = fit_calibration(
            samples,
            paints,
            opts,
            progress=lambda f, msg: update(progress=0.02 + 0.93 * f, message=msg),
        )
        d = fit_result_to_dict(result)
        with Session(engine) as s:
            last = s.exec(select(m.FittedModel).order_by(col(m.FittedModel.version).desc())).first()
            version = (last.version if last else 0) + 1
            if req.activate:
                for other in s.exec(select(m.FittedModel).where(col(m.FittedModel.active))).all():
                    other.active = False
                    s.add(other)
            fm = m.FittedModel(
                version=version,
                active=req.activate,
                paint_ids=d["paint_ids"],
                K=d["K"],
                S=d["S"],
                tau=d["tau"],
                k1=opts.k1,
                k2=opts.k2,
                substrate_white=d["substrate_white"],
                substrate_black=d["substrate_black"],
                diagnostics=clean_floats(
                    {**d["diagnostics"], "warnings": d["warnings"], "residuals": d["residuals"]}
                ),
                holdout_report=d["holdout"],
                n_samples=len(samples),
                fit_run_id=run_id,
                notes=req.notes,
            )
            s.add(fm)
            s.commit()
            s.refresh(fm)
            model_id = fm.id
        update(
            status="succeeded",
            progress=1.0,
            finished_at=utcnow(),
            model_id=model_id,
            message=f"model v{version} created" + (" and activated" if req.activate else ""),
        )
    except FitError as e:
        update(status="failed", error=str(e), finished_at=utcnow(), message="fit failed")
    except Exception as e:  # pragma: no cover - unexpected
        update(
            status="failed",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}",
            finished_at=utcnow(),
            message="fit crashed",
        )


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
    if session.exec(select(m.CalibrationSample)).first() is None:
        raise bad_request("no_samples", "upload calibration samples before fitting")
    run = m.FitRun(options=body.model_dump())
    session.add(run)
    session.commit()
    session.refresh(run)
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
