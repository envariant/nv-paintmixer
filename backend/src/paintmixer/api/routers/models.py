"""Fitted model versions: list, inspect, activate, spectra for plotting."""

from __future__ import annotations

import dataclasses
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import Response
from sqlmodel import Session, col, select

from paintmixer.api import events, matches
from paintmixer.api.compute import run_compute
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, not_found
from paintmixer.api.importers import store_swatch_model, swatch_inputs
from paintmixer.api.lines import (
    get_line,
    line_for_new_model,
    model_ref,
    move_to_line,
    resolve_model,
    set_active,
)
from paintmixer.api.schemas import (
    MAX_PAINTS_CAP,
    CoverageOut,
    GamutResponse,
    ModelDetail,
    ModelPatch,
    ModelSpectra,
    ModelSummary,
    PaintAccuracyOut,
    PaintSpectra,
    SampleErrorOut,
    StrengthOut,
    SwatchModelRequest,
    SwatchModelResult,
)
from paintmixer.api.services import (
    all_paints,
    check_max_paints,
    gamut_response,
    km_of,
    load_settings,
    model_paint_quality,
    model_strengths,
    pool_model,
)
from paintmixer.calibration.accuracy import grade, paint_status
from paintmixer.calibration.strength import PaintStrength, with_relative
from paintmixer.calibration.swatch import SwatchError, model_from_swatches
from paintmixer.colorsci.convert import reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.spectral import WAVELENGTHS
from paintmixer.db import models as m
from paintmixer.solver.gamut import Gamut
from paintmixer.solver.gamut_chart import gamut_svg
from paintmixer.solver.model import PoolModel
from paintmixer.solver.solve import gamut_for

router = APIRouter(prefix="/models", tags=["models"], responses=ERROR_RESPONSES)


def _strength_out(s: PaintStrength | None) -> StrengthOut | None:
    if s is None:
        return None
    return StrengthOut(
        reduction_fraction=s.reduction_fraction,
        reduction_ks=round(s.reduction_ks, 5),
        peak_nm=s.peak_nm,
        reduction_lab=[round(x, 3) for x in s.reduction_lab],
        reduction_hex=s.reduction_hex,
        relative_pct=None if s.relative_pct is None else round(s.relative_pct, 2),
    )


_REF = Path(
    description="Model ref: global version (12), line id (current model), line@3 or line@latest"
)


def _summary(session: Session, fm: m.FittedModel) -> dict[str, object]:
    line = session.get(m.ModelLine, fm.line_id)
    slug, name = (line.slug, line.name) if line else ("?", "?")
    return {
        "version": fm.version,
        "ref": model_ref(slug, fm.revision),
        "line": slug,
        "line_name": name,
        "revision": fm.revision,
        "label": fm.label,
        "active": fm.active,
        "source": fm.source,
        "created_at": fm.created_at,
        "paint_ids": fm.paint_ids,
        "n_samples": fm.n_samples,
        "k1": fm.k1,
        "k2": fm.k2,
        "illuminant": fm.illuminant,
        "observer": fm.observer,
        "holdout": fm.holdout_report,
        "warnings": fm.diagnostics.get("warnings", []),
        "notes": fm.notes,
    }


def summary(session: Session, fm: m.FittedModel) -> ModelSummary:
    return ModelSummary.model_validate(_summary(session, fm))


@router.get("", response_model=list[ModelSummary])
def list_models(
    session: SessionDep,
    line: str | None = Query(None, description="Only versions of this model line"),
) -> list[ModelSummary]:
    """All model versions, newest first."""
    q = select(m.FittedModel).order_by(col(m.FittedModel.version).desc())
    if line is not None:
        q = q.where(m.FittedModel.line_id == get_line(session, line).id)
    return [summary(session, fm) for fm in session.exec(q).all()]


@router.get("/active", response_model=ModelDetail)
def get_active(session: SessionDep) -> ModelDetail:
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    if fm is None:
        raise not_found("active model", "active")
    return get_model(str(fm.version), session)


@router.post(
    "/from-swatches",
    response_model=SwatchModelResult,
    status_code=201,
    dependencies=matches.REFRESH_AFTER,
)
async def model_from_swatch_colours(
    body: SwatchModelRequest, session: SessionDep, request: Request
) -> SwatchModelResult:
    """Build an **uncalibrated** model from each paint's swatch colours (``swatch_hex``, and
    optionally ``tint_hex`` / ``tint_fraction``), so recipes can be tried before calibrating.
    Expect several dE2000 of error; see docs/ASSUMPTIONS.md."""
    line = line_for_new_model(session, body.line)
    swatches = swatch_inputs(session, body.paint_ids)
    s = load_settings(session)
    try:
        sm = await run_compute(
            request.app,
            model_from_swatches,
            swatches,
            k1=s.saunderson_k1,
            k2=s.saunderson_k2,
            default_scattering=body.default_scattering,
        )
    except SwatchError as e:
        raise bad_request("swatch_model_failed", str(e)) from e
    fm = store_swatch_model(session, sm, body.activate, body.notes, line=line, label=body.label)
    return SwatchModelResult(
        model=summary(session, fm),
        scattering_source=sm.scattering_source,
        tint_match_de={k: round(v, 3) for k, v in sm.tint_match_de.items()},
        warnings=sm.warnings,
    )


@router.get("/{ref}", response_model=ModelDetail)
def get_model(ref: Annotated[str, _REF], session: SessionDep) -> ModelDetail:
    fm = resolve_model(session, ref)
    diag = {k: v for k, v in fm.diagnostics.items() if k not in ("warnings", "residuals")}
    return ModelDetail.model_validate(
        {
            **_summary(session, fm),
            "diagnostics": diag,
            "residuals": fm.diagnostics.get("residuals", []),
        }
    )


@router.patch("/{ref}", response_model=ModelSummary)
def update_model(ref: Annotated[str, _REF], body: ModelPatch, session: SessionDep) -> ModelSummary:
    """Edit a version's label or notes, or move it to another line (where it gets the next
    revision; its global version never changes). Spectra are immutable."""
    fm = resolve_model(session, ref)
    if body.label is not None:
        fm.label = body.label
    if body.notes is not None:
        fm.notes = body.notes
    if body.line is not None and body.line != getattr(
        session.get(m.ModelLine, fm.line_id), "slug", None
    ):
        move_to_line(session, fm, get_line(session, body.line))
    session.add(fm)
    session.commit()
    session.refresh(fm)
    return summary(session, fm)


@router.post("/{ref}/activate", response_model=ModelSummary, dependencies=matches.REFRESH_AFTER)
def activate_model(ref: Annotated[str, _REF], session: SessionDep) -> ModelSummary:
    """Make this the one active model (used by solve, predict, ramps and jobs)."""
    fm = resolve_model(session, ref)
    set_active(session, fm)
    session.commit()
    session.refresh(fm)
    announce_model(session, fm, "activated")
    return summary(session, fm)


def announce_model(session: Session, fm: m.FittedModel, kind: str) -> None:
    """``model`` event: a version was ``created`` (and maybe activated) or ``activated``."""
    events.publish(session, "model", {"event": kind, "model": summary(session, fm)})


@router.get("/{ref}/paint-accuracy", response_model=list[PaintAccuracyOut])
def paint_accuracy(ref: Annotated[str, _REF], session: SessionDep) -> list[PaintAccuracyOut]:
    """How well the model predicts each of its paints: the residual of every fitted sample with
    the paint, their median, a grade and a status (Models rack and paint card)."""
    fm = resolve_model(session, ref)
    quality = model_paint_quality(session, fm) if fm.source == "calibration" else {}
    paints = {p.id: p for p in all_paints(session)}
    batches = fm.paint_batches or {}
    out = []
    for pid in fm.paint_ids:
        q = quality.get(pid)
        p = paints.get(pid)
        now = p.batch_code if p is not None else None
        at_fit = batches.get(pid)
        # a blank batch at fit time is unknown: recording one later is not a change of lot
        changed = bool(at_fit) and now is not None and now != at_fit
        med = q.median_de if q is not None else None
        out.append(
            PaintAccuracyOut(
                paint_id=pid,
                name=p.name if p is not None else pid,
                samples=[
                    SampleErrorOut(
                        id=x.sample_id,
                        de2000=round(x.de2000, 4),
                        holdout=x.holdout,
                        outlier=x.outlier,
                        major=x.major,
                    )
                    for x in (q.samples if q is not None else [])
                ],
                median_de=None if med is None else round(med, 4),
                grade=None if med is None else grade(med),
                status=paint_status(q, changed),
                calibrated_at=fm.created_at,
                batch_at_fit=at_fit,
                batch_now=now,
                coverage=None
                if q is None
                else CoverageOut(**dataclasses.asdict(q.coverage), ok=q.coverage.ok),
            )
        )
    return out


@router.get("/{ref}/spectra", response_model=ModelSpectra)
def model_spectra(
    ref: Annotated[str, _REF],
    session: SessionDep,
    reference_version: str | None = Query(
        None, description="Model ref to compare tinting strength against (relative %)"
    ),
) -> ModelSpectra:
    """K, S, masstone and tinting strength of each paint (everything a client needs to run the
    forward model itself, together with ``GET /colorimetry``)."""
    fm = resolve_model(session, ref)
    km = km_of(fm)
    names = {p.id: p.name for p in all_paints(session)}
    strengths = model_strengths(session, fm)
    reference = resolve_model(session, reference_version) if reference_version else None
    if reference is not None:
        strengths = with_relative(strengths, model_strengths(session, reference))
    paints = []
    for i, pid in enumerate(fm.paint_ids):
        c = np.zeros(km.n_paints)
        c[i] = 1.0
        r = km.reflectance(c)
        paints.append(
            PaintSpectra(
                paint_id=pid,
                name=names.get(pid, pid),
                K=fm.K[i],
                S=fm.S[i],
                ks=(np.array(fm.K[i]) / np.array(fm.S[i])).round(6).tolist(),
                masstone=r.round(6).tolist(),
                masstone_hex=srgb_to_hex(reflectance_to_srgb(r).rgb),
                strength=_strength_out(strengths.get(pid)),
            )
        )
    return ModelSpectra(
        version=fm.version,
        k1=fm.k1,
        k2=fm.k2,
        reference_version=reference.version if reference is not None else None,
        wavelengths=WAVELENGTHS.tolist(),
        paints=paints,
        tau=fm.tau,
        substrate_white=fm.substrate_white,
        substrate_black=fm.substrate_black,
    )


_POOL_Q = Query(None, description="Comma-separated paint ids; default = every paint in the model")
_MAX_Q = Query(
    None,
    ge=1,
    le=MAX_PAINTS_CAP,
    description="Most paints per mixture (at most the model's paints); default = settings",
)


async def _model_gamut(
    request: Request, session: Session, ref: str, pool: str | None, max_paints: int | None
) -> tuple[PoolModel, m.FittedModel, Gamut, int]:
    fm = resolve_model(session, ref)
    ids = [p.strip() for p in pool.split(",") if p.strip()] if pool else None
    model, fm = pool_model(session, ids, fm)
    check_max_paints(max_paints, fm)
    k = max_paints or load_settings(session).max_paints
    g = await run_compute(request.app, gamut_for, model, k, fm.version)
    return model, fm, g, k


@router.get("/{ref}/gamut", response_model=GamutResponse)
async def model_gamut(
    ref: Annotated[str, _REF],
    session: SessionDep,
    request: Request,
    pool: str | None = _POOL_Q,
    max_paints: int | None = _MAX_Q,
) -> GamutResponse:
    """Colour reachability of any model version (active or not): the a*b* boundary per L*
    slice, with each boundary point's display colour, for charting or comparing versions."""
    model, fm, g, k = await _model_gamut(request, session, ref, pool, max_paints)
    return gamut_response(model, fm, g, k)


@router.get(
    "/{ref}/gamut.svg",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}, "description": "SVG chart"}},
)
async def model_gamut_svg(
    ref: Annotated[str, _REF],
    session: SessionDep,
    request: Request,
    pool: str | None = _POOL_Q,
    max_paints: int | None = _MAX_Q,
    columns: int = Query(5, ge=1, le=12, description="Panels per row"),
    chroma_scale: float | None = Query(
        None, gt=0, le=250, description="C* at the panel edge; fix it to compare versions"
    ),
) -> Response:
    """The same gamut as a ready-to-view SVG: one a*b* panel per L* slice on a neutral grey
    surround, wedges coloured from neutral to the boundary colour."""
    model, fm, g, k = await _model_gamut(request, session, ref, pool, max_paints)
    line = session.get(m.ModelLine, fm.line_id)
    where = model_ref(line.slug, fm.revision) if line else ""
    name = f" “{fm.label}”" if fm.label else ""
    title = (
        f"Gamut of model v{fm.version}{name} ({where}, {fm.source}"
        f"{', active' if fm.active else ''})"
    )
    sub = f"{', '.join(model.ids)} | up to {k} paints per mix | {g.n_samples} sampled mixtures"
    svg = gamut_svg(g, title, sub, columns, chroma_scale)
    return Response(svg, media_type="image/svg+xml")
