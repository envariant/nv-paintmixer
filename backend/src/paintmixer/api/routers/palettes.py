"""Palettes: named, ordered sets of colour-library entries."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlmodel import Session, col, select

from paintmixer.api import matches
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, not_found
from paintmixer.api.schemas import PaletteCreate, PaletteRead, PaletteSummary, PaletteUpdate
from paintmixer.db import models as m
from paintmixer.db.models import utcnow

router = APIRouter(prefix="/palettes", tags=["palettes"], responses=ERROR_RESPONSES)


def _existing(session: Session) -> set[int]:
    return {c for c in session.exec(select(m.ColorLibraryEntry.id)).all() if c is not None}


def _check(session: Session, ids: list[int]) -> list[int]:
    missing = [i for i in ids if i not in _existing(session)]
    if missing:
        raise bad_request("unknown_colors", f"colour ids not in the library: {missing}")
    return list(dict.fromkeys(ids))  # keep order, drop repeats


def _read(p: m.Palette, existing: set[int]) -> PaletteRead:
    # colours deleted from the library drop out of the palette silently
    return PaletteRead.model_validate(
        {**p.model_dump(), "color_ids": [i for i in p.color_ids if i in existing]}
    )


def _get(session: Session, palette_id: int) -> m.Palette:
    p = session.get(m.Palette, palette_id)
    if p is None:
        raise not_found("palette", palette_id)
    return p


@router.get("", response_model=list[PaletteRead])
def list_palettes(session: SessionDep) -> list[PaletteRead]:
    ex = _existing(session)
    q = select(m.Palette).order_by(col(m.Palette.name))
    return [_read(p, ex) for p in session.exec(q).all()]


@router.post("", response_model=PaletteRead, status_code=201)
def create_palette(body: PaletteCreate, session: SessionDep) -> PaletteRead:
    p = m.Palette(name=body.name, color_ids=_check(session, body.color_ids))
    session.add(p)
    session.commit()
    session.refresh(p)
    return _read(p, _existing(session))


@router.get("/{palette_id}", response_model=PaletteRead)
def get_palette(palette_id: int, session: SessionDep) -> PaletteRead:
    return _read(_get(session, palette_id), _existing(session))


@router.get("/{palette_id}/summary", response_model=PaletteSummary)
def palette_summary(palette_id: int, session: SessionDep, request: Request) -> PaletteSummary:
    """Reach of the palette's colours under the active model (the Library's palette band),
    from the cached library matches; ``pending`` counts those still being computed."""
    p = _get(session, palette_id)
    ex = _existing(session)
    ids = [i for i in p.color_ids if i in ex]
    entries = [e for i in ids if (e := session.get(m.ColorLibraryEntry, i)) is not None]
    fresh, missing = matches.fresh_matches(session, entries)
    if missing:
        matches.request_refresh(request.app)
    rows = list(fresh.values())
    return PaletteSummary(
        n=len(entries),
        within=sum(r.reach == "within" for r in rows),
        uncertain=sum(r.reach == "uncertain" for r in rows),
        out=sum(r.reach == "out" for r in rows),
        pending=missing,
        worst_de=max((r.de for r in rows), default=None),
    )


@router.patch("/{palette_id}", response_model=PaletteRead)
def update_palette(palette_id: int, body: PaletteUpdate, session: SessionDep) -> PaletteRead:
    p = _get(session, palette_id)
    if body.name is not None:
        p.name = body.name
    if body.color_ids is not None:
        p.color_ids = _check(session, body.color_ids)
    p.updated_at = utcnow()
    session.add(p)
    session.commit()
    session.refresh(p)
    return _read(p, _existing(session))


@router.delete("/{palette_id}", status_code=204)
def delete_palette(palette_id: int, session: SessionDep) -> Response:
    session.delete(_get(session, palette_id))
    session.commit()
    return Response(status_code=204)
