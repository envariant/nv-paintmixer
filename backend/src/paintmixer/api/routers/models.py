"""Fitted model versions: list, inspect, activate, spectra for plotting."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Query, Request
from sqlmodel import Session, col, select

from paintmixer.api.compute import run_compute
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request, not_found
from paintmixer.api.schemas import (
    ModelDetail,
    ModelSpectra,
    ModelSummary,
    PaintSpectra,
    StrengthOut,
    SwatchModelRequest,
    SwatchModelResult,
)
from paintmixer.api.services import all_paints, km_of, load_settings, model_strengths
from paintmixer.calibration.strength import PaintStrength, with_relative
from paintmixer.calibration.swatch import SwatchError, SwatchPaint, model_from_swatches
from paintmixer.colorsci.convert import hex_to_srgb, reflectance_to_srgb, srgb_to_hex, srgb_to_lab
from paintmixer.colorsci.spectral import WAVELENGTHS
from paintmixer.db import models as m
from paintmixer.domain import PaintRole

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


def _get(session: Session, version: int) -> m.FittedModel:
    fm = session.exec(select(m.FittedModel).where(m.FittedModel.version == version)).first()
    if fm is None:
        raise not_found("model version", version)
    return fm


def _summary(fm: m.FittedModel) -> dict[str, object]:
    return {
        "version": fm.version,
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


@router.get("", response_model=list[ModelSummary])
def list_models(session: SessionDep) -> list[ModelSummary]:
    rows = session.exec(select(m.FittedModel).order_by(col(m.FittedModel.version).desc())).all()
    return [ModelSummary.model_validate(_summary(fm)) for fm in rows]


@router.get("/active", response_model=ModelDetail)
def get_active(session: SessionDep) -> ModelDetail:
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    if fm is None:
        raise not_found("active model", "active")
    return get_model(fm.version, session)


@router.post("/from-swatches", response_model=SwatchModelResult, status_code=201)
async def model_from_swatch_colours(
    body: SwatchModelRequest, session: SessionDep, request: Request
) -> SwatchModelResult:
    """Build an **uncalibrated** model from each paint's swatch colours (``swatch_hex``, and
    optionally ``tint_hex`` / ``tint_fraction``), so recipes can be tried before calibrating.
    Expect several dE2000 of error; see docs/ASSUMPTIONS.md."""
    paints = {p.id: p for p in all_paints(session)}
    if body.paint_ids is None:
        ids = [p.id for p in paints.values() if p.active and p.swatch_hex]
    else:
        ids = body.paint_ids
    unknown = [i for i in ids if i not in paints]
    if unknown:
        raise bad_request("unknown_paint", f"unknown paint ids: {', '.join(unknown)}")
    missing = [i for i in ids if not paints[i].swatch_hex]
    if missing:
        raise bad_request(
            "missing_swatch", f"paints without swatch_hex: {', '.join(missing)}", missing
        )
    if not ids:
        raise bad_request("empty_pool", "no paints with swatch colours")
    swatches = [
        SwatchPaint(
            p.id,
            PaintRole(p.role),
            srgb_to_lab(hex_to_srgb(p.swatch_hex or "")),
            srgb_to_lab(hex_to_srgb(p.tint_hex)) if p.tint_hex else None,
            p.tint_fraction or 0.1,
        )
        for p in (paints[i] for i in ids)
    ]
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
    last = session.exec(select(m.FittedModel).order_by(col(m.FittedModel.version).desc())).first()
    if body.activate:
        for other in session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).all():
            other.active = False
            session.add(other)
    fm = m.FittedModel(
        version=(last.version if last else 0) + 1,
        active=body.activate,
        source="swatches",
        paint_ids=sm.paint_ids,
        K=np.round(sm.K, 7).tolist(),
        S=np.round(sm.S, 7).tolist(),
        tau=np.round(sm.tau, 9).tolist(),
        k1=sm.k1,
        k2=sm.k2,
        substrate_white=np.round(sm.substrate_white, 6).tolist(),
        substrate_black=np.round(sm.substrate_black, 6).tolist(),
        diagnostics={
            "warnings": sm.warnings,
            "scattering_source": sm.scattering_source,
            "tint_match_de": sm.tint_match_de,
        },
        holdout_report={
            "method": "none",
            "n_samples": 0,
            "mean_de": None,
            "median_de": None,
            "p95_de": None,
            "max_de": None,
            "mean_rms": None,
            "noise_floor_mean_de": None,
        },
        notes=body.notes or "uncalibrated: built from swatch colours",
    )
    session.add(fm)
    session.commit()
    session.refresh(fm)
    return SwatchModelResult(
        model=ModelSummary.model_validate(_summary(fm)),
        scattering_source=sm.scattering_source,
        tint_match_de={k: round(v, 3) for k, v in sm.tint_match_de.items()},
        warnings=sm.warnings,
    )


@router.get("/{version}", response_model=ModelDetail)
def get_model(version: int, session: SessionDep) -> ModelDetail:
    fm = _get(session, version)
    diag = {k: v for k, v in fm.diagnostics.items() if k not in ("warnings", "residuals")}
    return ModelDetail.model_validate(
        {**_summary(fm), "diagnostics": diag, "residuals": fm.diagnostics.get("residuals", [])}
    )


@router.post("/{version}/activate", response_model=ModelSummary)
def activate_model(version: int, session: SessionDep) -> ModelSummary:
    fm = _get(session, version)
    for other in session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).all():
        other.active = False
        session.add(other)
    fm.active = True
    session.add(fm)
    session.commit()
    session.refresh(fm)
    return ModelSummary.model_validate(_summary(fm))


@router.get("/{version}/spectra", response_model=ModelSpectra)
def model_spectra(
    version: int,
    session: SessionDep,
    reference_version: int | None = Query(
        None, description="Model version to compare tinting strength against (relative %)"
    ),
) -> ModelSpectra:
    """K, S, masstone and tinting strength of each paint (everything a client needs to run the
    forward model itself, together with ``GET /colorimetry``)."""
    fm = _get(session, version)
    km = km_of(fm)
    names = {p.id: p.name for p in all_paints(session)}
    strengths = model_strengths(session, fm)
    if reference_version is not None:
        strengths = with_relative(
            strengths, model_strengths(session, _get(session, reference_version))
        )
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
        reference_version=reference_version,
        wavelengths=WAVELENGTHS.tolist(),
        paints=paints,
        tau=fm.tau,
        substrate_white=fm.substrate_white,
        substrate_black=fm.substrate_black,
    )
