"""Paint library CRUD. ``loaded`` paints are the ones currently on the dispenser."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlmodel import Session, col, select

from paintmixer.api import matches
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, conflict, not_found
from paintmixer.api.importers import import_paints_csv, validate_paint
from paintmixer.api.schemas import (
    PaintCreate,
    PaintImportResult,
    PaintRead,
    PaintRefill,
    PaintUpdate,
)
from paintmixer.api.services import km_of, load_settings, model_strengths
from paintmixer.calibration.strength import PaintStrength
from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.db import models as m
from paintmixer.db.models import utcnow

router = APIRouter(prefix="/paints", tags=["paints"], responses=ERROR_RESPONSES)


@dataclass
class _ActiveInfo:
    calibrated: set[str]
    strengths: dict[str, PaintStrength]
    masstone: dict[str, tuple[list[float], str]]  # paint id -> (Lab D65, hex)
    low_level_pct: float = 25.0


def _calibrated_ids(session: Session) -> _ActiveInfo:
    low = load_settings(session).low_level_warn_pct
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    if fm is None:
        return _ActiveInfo(set(), {}, {}, low)
    km = km_of(fm)
    n = len(fm.paint_ids)
    masstone: dict[str, tuple[list[float], str]] = {}
    for i, pid in enumerate(fm.paint_ids):
        r = km.reflectance([1.0 if j == i else 0.0 for j in range(n)])
        lab = reflectance_to_lab(r)
        masstone[pid] = ([round(float(x), 4) for x in lab], srgb_to_hex(reflectance_to_srgb(r).rgb))
    return _ActiveInfo(set(fm.paint_ids), model_strengths(session, fm), masstone, low)


def _read(p: m.Paint, info: _ActiveInfo) -> PaintRead:
    st = info.strengths.get(p.id)
    pct = (
        round(100.0 * p.level_ml / p.capacity_ml, 1)
        if p.level_ml is not None and p.capacity_ml
        else None
    )
    lab, hex_ = info.masstone.get(p.id, (None, None))
    return PaintRead.model_validate(
        {
            **p.model_dump(),
            "calibrated": p.id in info.calibrated,
            "tinting_strength": st.reduction_ks if st else None,
            "tinting_peak_nm": st.peak_nm if st else None,
            "level_pct": pct,
            "low": pct is not None and pct < info.low_level_pct,
            "model_lab": lab,
            "model_hex": hex_,
        }
    )


@router.get("", response_model=list[PaintRead])
def list_paints(
    session: SessionDep,
    loaded: bool | None = Query(None),
    active: bool | None = Query(None),
    role: str | None = Query(None),
) -> list[PaintRead]:
    q = select(m.Paint).order_by(col(m.Paint.id))
    if loaded is not None:
        q = q.where(m.Paint.loaded == loaded)
    if active is not None:
        q = q.where(m.Paint.active == active)
    if role is not None:
        q = q.where(m.Paint.role == role)
    cal = _calibrated_ids(session)
    return [_read(p, cal) for p in session.exec(q).all()]


@router.post("", response_model=PaintRead, status_code=201, dependencies=matches.REFRESH_AFTER)
def create_paint(body: PaintCreate, session: SessionDep) -> PaintRead:
    if session.get(m.Paint, body.id) is not None:
        raise conflict(f"paint {body.id!r} already exists")
    p = m.Paint.model_validate(body.model_dump())
    validate_paint(session, p)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _read(p, _calibrated_ids(session))


@router.get("/{paint_id}", response_model=PaintRead)
def get_paint(paint_id: str, session: SessionDep) -> PaintRead:
    p = session.get(m.Paint, paint_id)
    if p is None:
        raise not_found("paint", paint_id)
    return _read(p, _calibrated_ids(session))


@router.patch("/{paint_id}", response_model=PaintRead, dependencies=matches.REFRESH_AFTER)
def update_paint(paint_id: str, body: PaintUpdate, session: SessionDep) -> PaintRead:
    p = session.get(m.Paint, paint_id)
    if p is None:
        raise not_found("paint", paint_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    p.updated_at = utcnow()
    validate_paint(session, p)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _read(p, _calibrated_ids(session))


@router.delete("/{paint_id}", status_code=204, dependencies=matches.REFRESH_AFTER)
def delete_paint(paint_id: str, session: SessionDep) -> Response:
    p = session.get(m.Paint, paint_id)
    if p is None:
        raise not_found("paint", paint_id)
    used = [
        s.id for s in session.exec(select(m.CalibrationSample)).all() if paint_id in s.components
    ]
    if used:
        raise conflict(
            f"paint {paint_id!r} is used by {len(used)} calibration samples; deactivate it instead",
            {"samples": used[:20]},
        )
    children = session.exec(select(m.Paint).where(m.Paint.parent_paint_id == paint_id)).all()
    if children:
        raise conflict(
            f"paint {paint_id!r} is the parent of diluted stocks", [c.id for c in children]
        )
    session.delete(p)
    session.commit()
    return Response(status_code=204)


@router.post("/import", response_model=PaintImportResult, dependencies=matches.REFRESH_AFTER)
async def import_paints(session: SessionDep, file: UploadFile = File(...)) -> PaintImportResult:
    """Upsert paints from CSV (columns as in ``sample_data/paints.csv``)."""
    return import_paints_csv(session, (await file.read()).decode("utf-8-sig"))


@router.post("/{paint_id}/refill", response_model=PaintRead)
def refill_paint(paint_id: str, body: PaintRefill, session: SessionDep) -> PaintRead:
    """Mark a reservoir refilled (Models screen). Records the time, and a new batch if given."""
    p = session.get(m.Paint, paint_id)
    if p is None:
        raise not_found("paint", paint_id)
    level = body.level_ml if body.level_ml is not None else p.capacity_ml
    if level is None:
        raise bad_request("no_capacity", "set capacity_ml on the paint or pass level_ml")
    if p.capacity_ml is not None and level > p.capacity_ml:
        raise bad_request("over_capacity", f"level exceeds capacity ({p.capacity_ml:g} ml)")
    p.level_ml = level
    p.last_refill_at = utcnow()
    if body.batch_code is not None:
        p.batch_code = body.batch_code
    p.updated_at = utcnow()
    session.add(p)
    session.commit()
    session.refresh(p)
    return _read(p, _calibrated_ids(session))
