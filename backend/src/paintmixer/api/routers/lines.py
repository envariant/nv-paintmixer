"""Model lines: named series of model versions (see :mod:`paintmixer.api.lines`)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlmodel import Session, col, select

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, ApiError
from paintmixer.api.lines import create_line, get_line, line_current, line_versions, model_ref
from paintmixer.api.routers.models import summary
from paintmixer.api.schemas import (
    ModelLineCreate,
    ModelLineDetail,
    ModelLinePatch,
    ModelLineSummary,
)
from paintmixer.db import models as m

router = APIRouter(prefix="/model-lines", tags=["models"], responses=ERROR_RESPONSES)


def _line_summary(session: Session, line: m.ModelLine) -> dict[str, object]:
    versions = line_versions(session, line)
    current = line_current(session, line)
    active = next((v for v in versions if v.active), None)
    return {
        "slug": line.slug,
        "name": line.name,
        "description": line.description,
        "created_at": line.created_at,
        "n_versions": len(versions),
        "current_version": current.version if current else None,
        "current_ref": model_ref(line.slug, current.revision) if current else None,
        "active_version": active.version if active else None,
    }


def _detail(session: Session, line: m.ModelLine) -> ModelLineDetail:
    return ModelLineDetail.model_validate(
        {
            **_line_summary(session, line),
            "versions": [summary(session, fm) for fm in line_versions(session, line)],
        }
    )


@router.get("", response_model=list[ModelLineSummary])
def list_lines(session: SessionDep) -> list[ModelLineSummary]:
    lines = session.exec(select(m.ModelLine).order_by(col(m.ModelLine.slug))).all()
    return [ModelLineSummary.model_validate(_line_summary(session, ln)) for ln in lines]


@router.post("", response_model=ModelLineDetail, status_code=201)
def new_line(body: ModelLineCreate, session: SessionDep) -> ModelLineDetail:
    """Create an empty line; fits and swatch models are added to it with ``"line": <id>``."""
    return _detail(session, create_line(session, body.name, body.slug, body.description))


@router.get("/{slug}", response_model=ModelLineDetail)
def get_model_line(slug: str, session: SessionDep) -> ModelLineDetail:
    return _detail(session, get_line(session, slug))


@router.patch("/{slug}", response_model=ModelLineDetail)
def update_line(slug: str, body: ModelLinePatch, session: SessionDep) -> ModelLineDetail:
    """Rename or re-describe a line. Its id is fixed, so refs keep working."""
    line = get_line(session, slug)
    if body.name is not None:
        line.name = body.name
    if body.description is not None:
        line.description = body.description
    session.add(line)
    session.commit()
    session.refresh(line)
    return _detail(session, line)


@router.delete("/{slug}", status_code=204, response_class=Response)
def delete_line(slug: str, session: SessionDep) -> Response:
    """Delete an empty line. Models are never deleted: move them out first."""
    line = get_line(session, slug)
    n = len(line_versions(session, line))
    if n:
        raise ApiError(
            409, "line_not_empty", f"model line {slug!r} has {n} versions", {"n_versions": n}
        )
    session.delete(line)
    session.commit()
    return Response(status_code=204)
