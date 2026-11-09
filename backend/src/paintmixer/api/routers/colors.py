"""Colour library CRUD and CSV import."""

from __future__ import annotations

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlmodel import col, select

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, conflict, not_found
from paintmixer.api.importers import import_colors_csv
from paintmixer.api.schemas import ColorCreate, ColorImportResult, ColorRead, ColorUpdate
from paintmixer.api.services import color_from_input
from paintmixer.colorsci.convert import lab_to_srgb
from paintmixer.db import models as m

router = APIRouter(prefix="/colors", tags=["color library"], responses=ERROR_RESPONSES)


def _read(e: m.ColorLibraryEntry) -> ColorRead:
    import numpy as np

    return ColorRead(
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
    q: str | None = Query(None, description="Case-insensitive substring of the name"),
    source: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> list[ColorRead]:
    stmt = select(m.ColorLibraryEntry).order_by(
        col(m.ColorLibraryEntry.source), col(m.ColorLibraryEntry.name)
    )
    if q:
        stmt = stmt.where(col(m.ColorLibraryEntry.name).icontains(q))
    if source is not None:
        stmt = stmt.where(m.ColorLibraryEntry.source == source)
    return [_read(e) for e in session.exec(stmt.offset(offset).limit(limit)).all()]


@router.post("", response_model=ColorRead, status_code=201)
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


@router.patch("/{color_id}", response_model=ColorRead)
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
    e = session.get(m.ColorLibraryEntry, color_id)
    if e is None:
        raise not_found("colour", color_id)
    session.delete(e)
    session.commit()
    return Response(status_code=204)


@router.post("/import", response_model=ColorImportResult)
async def import_colors(
    session: SessionDep,
    file: UploadFile = File(...),
    source: str | None = Query(None, description="Override the source column"),
) -> ColorImportResult:
    """CSV columns: ``name``, ``source`` (optional) and one of ``hex`` | ``r,g,b`` (0-255) |
    ``L,a,b`` (D65) | ``r380..r730``. Existing (source, name) pairs are updated."""
    return import_colors_csv(session, (await file.read()).decode("utf-8-sig"), source)
