"""Paint library CRUD. ``loaded`` paints are the ones currently on the dispenser."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, File, Query, Response, UploadFile
from pydantic import ValidationError
from sqlmodel import Session, col, select

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, conflict, not_found
from paintmixer.api.schemas import PaintCreate, PaintImportResult, PaintRead, PaintUpdate
from paintmixer.api.services import load_settings
from paintmixer.db import models as m
from paintmixer.db.models import utcnow

router = APIRouter(prefix="/paints", tags=["paints"], responses=ERROR_RESPONSES)


def _calibrated_ids(session: Session) -> set[str]:
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    return set(fm.paint_ids) if fm else set()


def _read(p: m.Paint, calibrated: set[str]) -> PaintRead:
    return PaintRead.model_validate({**p.model_dump(), "calibrated": p.id in calibrated})


def _check(session: Session, p: m.Paint) -> None:
    if p.loaded:
        if p.dispenser_channel is None:
            raise bad_request("channel_required", "a loaded paint needs a dispenser_channel")
        n_ch = load_settings(session).dispenser_channels
        if p.dispenser_channel > n_ch:
            raise bad_request(
                "channel_out_of_range", f"dispenser_channel must be 1-{n_ch} (settings)"
            )
        clash = session.exec(
            select(m.Paint).where(
                col(m.Paint.loaded),
                m.Paint.dispenser_channel == p.dispenser_channel,
                m.Paint.id != p.id,
            )
        ).first()
        if clash is not None:
            raise conflict(
                f"channel {p.dispenser_channel} is already used by loaded paint {clash.id!r}",
                {"paint_id": clash.id},
            )
    if (p.parent_paint_id is None) != (p.dilution is None):
        raise bad_request(
            "bad_dilution", "parent_paint_id and dilution must be given together for a stock"
        )
    if p.parent_paint_id is not None:
        if p.parent_paint_id == p.id:
            raise bad_request("bad_dilution", "a paint cannot be its own parent")
        if session.get(m.Paint, p.parent_paint_id) is None:
            raise bad_request("unknown_paint", f"parent paint {p.parent_paint_id!r} not found")


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


@router.post("", response_model=PaintRead, status_code=201)
def create_paint(body: PaintCreate, session: SessionDep) -> PaintRead:
    if session.get(m.Paint, body.id) is not None:
        raise conflict(f"paint {body.id!r} already exists")
    p = m.Paint.model_validate(body.model_dump())
    _check(session, p)
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


@router.patch("/{paint_id}", response_model=PaintRead)
def update_paint(paint_id: str, body: PaintUpdate, session: SessionDep) -> PaintRead:
    p = session.get(m.Paint, paint_id)
    if p is None:
        raise not_found("paint", paint_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    p.updated_at = utcnow()
    _check(session, p)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _read(p, _calibrated_ids(session))


@router.delete("/{paint_id}", status_code=204)
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


@router.post("/import", response_model=PaintImportResult)
async def import_paints(session: SessionDep, file: UploadFile = File(...)) -> PaintImportResult:
    """Upsert paints from CSV (columns as in ``sample_data/paints.csv``)."""
    text = (await file.read()).decode("utf-8-sig")
    created: list[str] = []
    updated: list[str] = []
    errors: list[str] = []
    rows = list(csv.DictReader(io.StringIO(text)))
    # place unloaded rows first so channel moves inside one file do not clash
    rows.sort(key=lambda r: (r.get("loaded", "").strip().lower() in ("1", "true", "yes"),))
    for n, r in enumerate(rows, start=2):
        data: dict[str, object] = {k: v for k, v in r.items() if k and v not in (None, "")}
        for b in ("loaded", "active"):
            if b in data:
                data[b] = str(data[b]).strip().lower() in ("1", "true", "yes")
        try:
            body = PaintCreate.model_validate(data)
            existing = session.get(m.Paint, body.id)
            p = existing or m.Paint(id=body.id, name=body.name)
            for k, v in body.model_dump().items():
                setattr(p, k, v)
            _check(session, p)
            session.add(p)
            session.commit()
            (updated if existing else created).append(body.id)
        except ValidationError as e:
            session.rollback()
            errors.append(f"row {n}: {e.errors()[0]['loc']}: {e.errors()[0]['msg']}")
        except Exception as e:  # ApiError from _check
            session.rollback()
            errors.append(f"row {n}: {getattr(e, 'message', str(e))}")
    return PaintImportResult(created=created, updated=updated, errors=errors)
