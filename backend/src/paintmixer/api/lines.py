"""Model lines and model references.

A *line* is a named series of model versions, typically one paint set recalibrated over time
("cmykw-studio"). Every version keeps its global ``version`` number and also gets a
``revision`` within its line. Anywhere the API takes a model, it accepts a *ref*:

* ``12``: global version 12;
* ``cmykw-studio``: the line's *current* model, its newest calibrated revision (or its newest
  revision if none is calibrated);
* ``cmykw-studio@3``: revision 3 of the line;
* ``cmykw-studio@latest``: the newest revision of any source.
"""

from __future__ import annotations

import re

from sqlmodel import Session, col, select

from paintmixer.api.errors import ApiError, bad_request, not_found
from paintmixer.db import models as m

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
RESERVED_SLUGS = frozenset({"active", "from-swatches"})  # fixed paths under /models
DEFAULT_LINE = "default"


def slugify(name: str) -> str:
    """URL-safe line id from a display name: lower case, runs of other characters -> '-'."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:56].strip("-")
    if not s:
        return "line"
    return s if s[0].isalpha() else f"line-{s}"


def check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise bad_request(
            "invalid_slug",
            f"line id {slug!r} must be lower case letters, digits and '-', starting with a letter",
        )
    if slug in RESERVED_SLUGS:
        raise bad_request("invalid_slug", f"line id {slug!r} is reserved")
    return slug


def find_line(session: Session, slug: str) -> m.ModelLine | None:
    return session.exec(select(m.ModelLine).where(m.ModelLine.slug == slug)).first()


def get_line(session: Session, slug: str) -> m.ModelLine:
    line = find_line(session, slug)
    if line is None:
        raise not_found("model line", slug)
    return line


def create_line(
    session: Session, name: str, slug: str | None = None, description: str = ""
) -> m.ModelLine:
    slug = check_slug(slug or slugify(name))
    if find_line(session, slug) is not None:
        raise ApiError(409, "line_exists", f"model line {slug!r} already exists", {"slug": slug})
    line = m.ModelLine(slug=slug, name=name.strip() or slug, description=description)
    session.add(line)
    session.commit()
    session.refresh(line)
    return line


def line_for_new_model(session: Session, slug: str | None) -> m.ModelLine:
    """The line a new model goes into: ``slug`` (must exist) or the auto-created default."""
    if slug is None or slug == DEFAULT_LINE:
        line = find_line(session, DEFAULT_LINE)
        if line is None:
            line = m.ModelLine(slug=DEFAULT_LINE, name="Default")
            session.add(line)
            session.commit()
            session.refresh(line)
        return line
    line = find_line(session, slug)
    if line is None:
        raise bad_request(
            "unknown_line", f"no model line {slug!r}: create it with POST /model-lines", slug
        )
    return line


def line_versions(session: Session, line: m.ModelLine) -> list[m.FittedModel]:
    """All versions of a line, newest revision first."""
    return list(
        session.exec(
            select(m.FittedModel)
            .where(m.FittedModel.line_id == line.id)
            .order_by(col(m.FittedModel.revision).desc())
        ).all()
    )


def line_current(session: Session, line: m.ModelLine) -> m.FittedModel | None:
    versions = line_versions(session, line)
    calibrated = [v for v in versions if v.source == "calibration"]
    pick = calibrated or versions
    return pick[0] if pick else None


def place_model(session: Session, fm: m.FittedModel, line: m.ModelLine) -> None:
    """Give a new model the next global version and the next revision in ``line``."""
    last = session.exec(select(m.FittedModel).order_by(col(m.FittedModel.version).desc())).first()
    fm.version = (last.version if last else 0) + 1
    move_to_line(session, fm, line)


def move_to_line(session: Session, fm: m.FittedModel, line: m.ModelLine) -> None:
    """Put ``fm`` in ``line`` with a fresh revision (the caller commits)."""
    assert line.id is not None
    line.last_revision += 1
    session.add(line)
    fm.line_id = line.id
    fm.revision = line.last_revision


def set_active(session: Session, fm: m.FittedModel) -> None:
    """Make ``fm`` the one active model (the caller commits)."""
    for other in session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).all():
        if other.id != fm.id:
            other.active = False
            session.add(other)
    fm.active = True
    session.add(fm)


def resolve_model(session: Session, ref: str) -> m.FittedModel:
    """The model a ref names (see the module docstring); 404 if there is none."""
    ref = ref.strip()
    if ref.isdigit():
        fm = session.exec(select(m.FittedModel).where(m.FittedModel.version == int(ref))).first()
        if fm is None:
            raise not_found("model version", int(ref))
        return fm
    slug, _, rev = ref.partition("@")
    line = get_line(session, slug)
    if not rev:
        found = line_current(session, line)
    elif rev == "latest":
        found = next(iter(line_versions(session, line)), None)
    elif rev.isdigit():
        found = session.exec(
            select(m.FittedModel).where(
                m.FittedModel.line_id == line.id, m.FittedModel.revision == int(rev)
            )
        ).first()
    else:
        raise bad_request(
            "invalid_ref", f"bad model ref {ref!r}: use 12, line, line@3 or line@latest"
        )
    if found is None:
        raise not_found("model", ref)
    return found


def model_ref(line_slug: str, revision: int) -> str:
    return f"{line_slug}@{revision}"
