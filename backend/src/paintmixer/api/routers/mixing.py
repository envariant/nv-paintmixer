"""Recipe solving, forward prediction and gamut data.

These endpoints are plain ``def`` so FastAPI runs them in its worker thread pool: the NumPy/SciPy
work never blocks the event loop.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Query

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request
from paintmixer.api.schemas import (
    CandidateOut,
    ComponentOut,
    GamutResponse,
    GamutSliceOut,
    PredictRequest,
    PredictResponse,
    SolveRequest,
    SolveResponse,
)
from paintmixer.api.services import (
    ILLUMINANTS_REPORTED,
    load_settings,
    pool_model,
    resolve_target,
)
from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.spectral import WAVELENGTHS
from paintmixer.solver.refine import Weights
from paintmixer.solver.solve import Candidate, SolveOptions, gamut_for, predict, solve

router = APIRouter(tags=["mixing"], responses=ERROR_RESPONSES)


def candidate_out(
    c: Candidate, names: dict[str, str], cost: dict[str, float], currency: str
) -> CandidateOut:
    comps = [
        ComponentOut(
            paint_id=pid,
            name=names.get(pid, pid),
            fraction=c.fractions_quantised[i],
            fraction_continuous=c.fractions[i],
            volume_ml=c.volumes_ml[i],
            mass_g=c.masses_g[i],
            cost=c.volumes_ml[i] * cost.get(pid, 0.0),
        )
        for i, pid in enumerate(c.paint_ids)
    ]
    return CandidateOut(
        rank=c.rank,
        components=comps,
        predicted_spectrum=[round(x, 6) for x in c.predicted_spectrum],
        predicted_lab=[round(x, 4) for x in c.predicted_lab],
        predicted_hex=c.predicted_hex,
        de2000=c.de2000,
        de2000_continuous=c.de2000_continuous,
        cost=c.cost,
        cost_per_ml=c.cost_per_ml,
        currency=currency,
        metamerism=c.metamerism,
        dose_sensitivity=c.dose_sensitivity,
        objective=c.objective,
        warnings=c.warnings,
    )


@router.post("/solve", response_model=SolveResponse)
def solve_recipe(body: SolveRequest, session: SessionDep) -> SolveResponse:
    s = load_settings(session)
    model, fm = pool_model(session, body.pool)
    target = resolve_target(session, body.target)
    w = body.weights or s.weights
    opts = SolveOptions(
        max_paints=body.max_paints or s.max_paints,
        min_fraction=body.min_fraction if body.min_fraction is not None else s.min_fraction,
        include_white=body.include_white,
        illuminant=body.illuminant or s.illuminant,
        batch_volume_ml=body.batch_volume_ml or s.batch_volume_ml,
        resolution_ml=body.resolution_ml or s.dispenser_resolution_ml,
        weights=Weights(de=w.de, n_paints=w.n_paints, cost=w.cost, metamerism=w.metamerism),
        top_n=body.top_n or s.top_n,
        seed=body.seed if body.seed is not None else s.seed,
        search=body.search,
        out_of_gamut_de=s.out_of_gamut_de,
    )
    if opts.max_paints * opts.min_fraction > 1:
        raise bad_request("bad_constraints", "max_paints x min_fraction must be <= 1")
    res = solve(model, target, opts, gamut_cache_key=fm.version)
    names = {p.id: p.name for p in model.paints}
    cost = {p.id: p.cost_per_ml for p in model.paints}
    return SolveResponse(
        target_name=target.name,
        target_lab=[round(x, 4) for x in res.target_lab],
        target_hex=res.target_hex,
        target_in_srgb_gamut=res.target_in_srgb_gamut,
        reference_spectrum=[round(x, 6) for x in res.reference_spectrum],
        reference_spectrum_source=res.reference_spectrum_source,
        candidates=[candidate_out(c, names, cost, s.currency) for c in res.candidates],
        in_gamut=res.in_gamut,
        nearest_de=res.nearest_de,
        warnings=res.warnings,
        search=res.search,
        n_subsets=res.n_subsets,
        duration_s=res.duration_s,
        model_version=fm.version,
        pool=model.ids,
        batch_volume_ml=opts.batch_volume_ml,
        illuminant=opts.illuminant.value,
    )


@router.post("/predict", response_model=PredictResponse)
def predict_mixture(body: PredictRequest, session: SessionDep) -> PredictResponse:
    """Forward model: predicted opaque-film spectrum and colour of a given mixture."""
    if any(v < 0 for v in body.components.values()) or sum(body.components.values()) <= 0:
        raise bad_request("bad_components", "fractions must be >= 0 with a positive sum")
    model, fm = pool_model(session, list(body.components))
    r = predict(model, list(body.components), list(body.components.values()))
    srgb = reflectance_to_srgb(r)
    return PredictResponse(
        wavelengths=WAVELENGTHS.tolist(),
        spectrum=r.round(6).tolist(),
        lab={
            ill.value: reflectance_to_lab(r, ill).round(4).tolist() for ill in ILLUMINANTS_REPORTED
        },
        hex=srgb_to_hex(srgb.rgb),
        out_of_srgb_gamut=bool(srgb.out_of_gamut),
        model_version=fm.version,
    )


@router.get("/gamut", response_model=GamutResponse)
def gamut(
    session: SessionDep,
    pool: str | None = Query(None, description="Comma-separated paint ids; default = loaded"),
    max_paints: int | None = Query(None, ge=1, le=8),
) -> GamutResponse:
    """a*b* boundary (max chroma per 10° hue bin) at L* slices every 10 units."""
    ids = [p.strip() for p in pool.split(",") if p.strip()] if pool else None
    model, fm = pool_model(session, ids)
    k = max_paints or load_settings(session).max_paints
    g = gamut_for(model, k, cache_key=fm.version)
    return GamutResponse(
        pool=model.ids,
        L_min=g.L_min,
        L_max=g.L_max,
        n_samples=g.n_samples,
        model_version=fm.version,
        slices=[
            GamutSliceOut(
                L=sl.L,
                hue_deg=sl.hue_deg.tolist(),
                chroma=np.round(sl.chroma, 3).tolist(),
                a=np.round(sl.a, 3).tolist(),
                b=np.round(sl.b, 3).tolist(),
            )
            for sl in g.slices
        ],
    )
