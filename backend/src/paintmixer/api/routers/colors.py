"""Colour library CRUD and CSV import."""

from __future__ import annotations

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from sqlmodel import col, select

from paintmixer.api import matches
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, conflict, not_found
from paintmixer.api.importers import import_colors_csv
from paintmixer.api.schemas import (
    ColorCreate,
    ColorImportResult,
    ColorMatchOut,
    ColorRead,
    ColorUpdate,
)
from paintmixer.api.services import color_from_input
from paintmixer.colorsci.convert import lab_to_srgb
from paintmixer.db import models as m
from paintmixer.db.models import utcnow

router = APIRouter(prefix="/colors", tags=["color library"], responses=ERROR_RESPONSES)


def _match(row: m.ColorMatch) -> ColorMatchOut:
    return ColorMatchOut.model_validate(row, from_attributes=True)


def _read(e: m.ColorLibraryEntry, match: m.ColorMatch | None = None) -> ColorRead:
    import numpy as np

    return ColorRead(
        match=None if match is None else _match(match),
        id=e.id or 0,
        name=e.name,
        source=e.source,
        hex=e.hex,
        srgb=e.srgb,
        lab=e.lab,
        spectrum=e.spectrum,
        in_srgb_gamut=not bool(lab_to_srgb(np.array(e.lab)).out_of_gamut),
        notes=e.notes,
    )


@router.get("", response_model=list[ColorRead])
def list_colors(
    session: SessionDep,
    request: Request,
    q: str | None = Query(None, description="Case-insensitive substring of the name"),
    source: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    with_match: bool = Query(
        False, description="Add each colour's cached closest mix (null while it is computed)"
    ),
) -> list[ColorRead]:
    stmt = select(m.ColorLibraryEntry).order_by(
        col(m.ColorLibraryEntry.source), col(m.ColorLibraryEntry.name)
    )
    if q:
        stmt = stmt.where(col(m.ColorLibraryEntry.name).icontains(q))
    if source is not None:
        stmt = stmt.where(m.ColorLibraryEntry.source == source)
    entries = list(session.exec(stmt.offset(offset).limit(limit)).all())
    if not with_match:
        return [_read(e) for e in entries]
    fresh, missing = matches.fresh_matches(session, entries)
    if missing:
        matches.request_refresh(request.app)
    return [_read(e, fresh.get(e.id or 0)) for e in entries]


@router.post("", response_model=ColorRead, status_code=201, dependencies=matches.REFRESH_AFTER)
def create_color(body: ColorCreate, session: SessionDep) -> ColorRead:
    dup = session.exec(
        select(m.ColorLibraryEntry).where(
            m.ColorLibraryEntry.name == body.name, m.ColorLibraryEntry.source == body.source
        )
    ).first()
    if dup is not None:
        raise conflict(f"colour {body.name!r} already exists in source {body.source!r}")
    lab, rgb, hx, _ = color_from_input(body.hex, body.srgb, body.lab, body.spectrum)
    e = m.ColorLibraryEntry(
        name=body.name,
        source=body.source,
        hex=hx,
        srgb=rgb,
        lab=lab,
        spectrum=body.spectrum,
        notes=body.notes,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return _read(e)


@router.get("/{color_id}", response_model=ColorRead)
def get_color(color_id: int, session: SessionDep) -> ColorRead:
    e = session.get(m.ColorLibraryEntry, color_id)
    if e is None:
        raise not_found("colour", color_id)
    return _read(e)


@router.patch("/{color_id}", response_model=ColorRead, dependencies=matches.REFRESH_AFTER)
def update_color(color_id: int, body: ColorUpdate, session: SessionDep) -> ColorRead:
    e = session.get(m.ColorLibraryEntry, color_id)
    if e is None:
        raise not_found("colour", color_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("name", "source", "notes"):
        if k in data and data[k] is not None:
            setattr(e, k, data[k])
    if any(data.get(k) is not None for k in ("hex", "lab", "spectrum")):
        lab, rgb, hx, _ = color_from_input(
            data.get("hex"), None, data.get("lab"), data.get("spectrum")
        )
        e.lab, e.srgb, e.hex = lab, rgb, hx
        e.spectrum = data.get("spectrum")
    session.add(e)
    session.commit()
    session.refresh(e)
    return _read(e)


@router.delete("/{color_id}", status_code=204)
def delete_color(color_id: int, session: SessionDep) -> Response:
    """Delete a colour and remove it from every palette. SQLite can give a later colour the
    same id, so a stale id left in a palette would bring in an unrelated colour."""
    e = session.get(m.ColorLibraryEntry, color_id)
    if e is None:
        raise not_found("colour", color_id)
    row = session.get(m.ColorMatch, color_id)
    if row is not None:
        session.delete(row)
    for pal in session.exec(select(m.Palette)).all():
        if color_id in pal.color_ids:
            pal.color_ids = [i for i in pal.color_ids if i != color_id]
            pal.updated_at = utcnow()
            session.add(pal)
    session.delete(e)
    session.commit()
    return Response(status_code=204)


@router.post("/import", response_model=ColorImportResult, dependencies=matches.REFRESH_AFTER)
async def import_colors(
    session: SessionDep,
    file: UploadFile = File(...),
    source: str | None = Query(None, description="Override the source column"),
) -> ColorImportResult:
    """CSV columns: ``name``, ``source`` (optional) and one of ``hex`` | ``r,g,b`` (0-255) |
    ``L,a,b`` (D65) | ``r380..r730``. Existing (source, name) pairs are updated."""
    return import_colors_csv(session, (await file.read()).decode("utf-8-sig"), source)
