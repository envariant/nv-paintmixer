"""Recipe solving, forward prediction and gamut data.

Solve and gamut run through :func:`paintmixer.api.compute.run_compute` (process pool, or thread
pool when ``compute_workers`` is 0), so the event loop is never blocked.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from fastapi import APIRouter, Query, Request

from paintmixer.api.compute import run_compute
from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request
from paintmixer.api.schemas import (
    CandidateOut,
    ComponentOut,
    GamutResponse,
    MixCellOut,
    MultimixRequest,
    MultimixResponse,
    PredictRequest,
    PredictResponse,
    RampRequest,
    RampResponse,
    RampStepOut,
    SolveRequest,
    SolveResponse,
)
from paintmixer.api.services import (
    ILLUMINANTS_REPORTED,
    active_model,
    all_paints,
    default_solve_options,
    gamut_response,
    load_settings,
    pool_model,
    resolve_target,
)
from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.spectral import WAVELENGTHS
from paintmixer.solver.multimix import (
    MultimixError,
    grid_parts,
    multimix,
    polygon_layout,
    simplex_lattice,
)
from paintmixer.solver.ramp import ramp, ramp_fractions
from paintmixer.solver.refine import Weights
from paintmixer.solver.solve import Candidate, gamut_for, predict, solve

router = APIRouter(tags=["mixing"], responses=ERROR_RESPONSES)

SWATCH_MODEL_WARNING = (
    "The active model is built from swatch colours, not calibration measurements: predictions "
    "and recipes are rough (typically several dE2000 off). Calibrate for accurate recipes."
)


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
        tags=c.tags,
        uncertainty_de=None if c.uncertainty_de is None else round(c.uncertainty_de, 3),
    )


@router.post("/solve", response_model=SolveResponse)
async def solve_recipe(body: SolveRequest, session: SessionDep, request: Request) -> SolveResponse:
    s = load_settings(session)
    model, fm = pool_model(session, body.pool)
    target = resolve_target(session, body.target)
    base = default_solve_options(session, s, fm)
    w = body.weights
    opts = replace(
        base,
        max_paints=body.max_paints or base.max_paints,
        min_fraction=body.min_fraction if body.min_fraction is not None else base.min_fraction,
        include_white=body.include_white,
        illuminant=body.illuminant or base.illuminant,
        batch_volume_ml=body.batch_volume_ml or base.batch_volume_ml,
        resolution_ml=body.resolution_ml or base.resolution_ml,
        weights=base.weights
        if w is None
        else Weights(de=w.de, n_paints=w.n_paints, cost=w.cost, metamerism=w.metamerism),
        top_n=body.top_n or base.top_n,
        seed=body.seed if body.seed is not None else base.seed,
        search=body.search,
    )
    if opts.batch_volume_ml > s.machine_max_batch_ml:
        raise bad_request(
            "batch_too_large",
            f"batch_volume_ml exceeds the machine maximum ({s.machine_max_batch_ml:g} ml)",
        )
    if opts.max_paints * opts.min_fraction > 1:
        raise bad_request("bad_constraints", "max_paints x min_fraction must be <= 1")
    res = await run_compute(request.app, solve, model, target, opts, gamut_cache_key=fm.version)
    if fm.source == "swatches":
        res.warnings.insert(0, SWATCH_MODEL_WARNING)
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
        gamut_margin_de=None if res.gamut_margin_de is None else round(res.gamut_margin_de, 3),
        warnings=res.warnings,
        search=res.search,
        n_subsets=res.n_subsets,
        duration_s=res.duration_s,
        model_version=fm.version,
        model_source=fm.source,
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
        model_source=fm.source,
    )


@router.post("/ramp", response_model=RampResponse)
def palette_ramp(body: RampRequest, session: SessionDep) -> RampResponse:
    """Predicted swatches mixing paint A into paint B (default: white, i.e. a tint ladder).

    A shortcut for the commonest two-paint preview. ``scale: "log"`` dilutes paint A by the same
    factor at every step (a tint ladder); a ``linear`` ramp of ``n`` steps equals
    ``POST /multimix`` with these two paints and ``divisions = n - 1``.
    """
    fm = active_model(session)
    roles = {p.id: p.role for p in all_paints(session)}
    b = body.paint_b
    if b is None:
        whites = [p for p in fm.paint_ids if roles.get(p) == "white"]
        if not whites:
            raise bad_request("no_white", "the active model has no white; give paint_b")
        b = whites[0]
    if b == body.paint_a:
        raise bad_request("same_paint", "paint_a and paint_b must differ")
    model, fm = pool_model(session, [body.paint_a, b])
    try:
        fr = ramp_fractions(body.steps, body.scale, body.min_fraction)
    except ValueError as e:
        raise bad_request("bad_ramp", str(e)) from e
    steps = ramp(model.km, 0, 1, fr)
    return RampResponse(
        paint_a=body.paint_a,
        paint_b=b,
        model_version=fm.version,
        model_source=fm.source,
        steps=[
            RampStepOut(
                fraction_a=round(s.fraction_a, 6),
                lab=[round(x, 4) for x in s.lab],
                hex=s.hex,
                out_of_srgb_gamut=s.out_of_srgb_gamut,
                spectrum=s.reflectance.round(6).tolist(),
            )
            for s in steps
        ],
    )


@router.post("/multimix", response_model=MultimixResponse)
def multimix_array(body: MultimixRequest, session: SessionDep) -> MultimixResponse:
    """Predicted swatches for every mix of 2-6 paints: a simplex lattice or an N-D grid of levels.

    Use it to explore a palette: e.g. ``simplex`` with 3 paints and 10 divisions is the classic
    mixing triangle (66 cells); ``grid`` with ``levels`` per paint is an N-dimensional array that
    keeps its shape for slicing (``shape``, cell ``index``).
    """
    model, fm = pool_model(session, body.paint_ids)
    try:
        if body.mode == "simplex":
            parts = simplex_lattice(len(body.paint_ids), body.divisions, body.interior_only)
            shape = [int(parts.shape[0])]
            index = parts.astype(float)
        else:
            assert body.levels is not None
            grid_shape, parts = grid_parts(body.levels)
            shape = list(grid_shape)
            index = np.array(list(np.ndindex(*grid_shape)), dtype=float).reshape(len(parts), -1)
    except MultimixError as e:
        raise bad_request("bad_multimix", str(e)) from e
    cells = multimix(model.km, list(range(model.n)), parts)
    k = len(body.paint_ids)
    return MultimixResponse(
        paints=model.ids,
        mode=body.mode,
        shape=shape,
        n_cells=len(cells),
        model_version=fm.version,
        model_source=fm.source,
        vertices=np.round(polygon_layout(np.eye(k)), 9).tolist(),
        cells=[
            MixCellOut(
                index=index[i].tolist(),
                parts=list(c.parts),
                fractions=None if c.fractions is None else [round(x, 9) for x in c.fractions],
                lab=None if c.lab is None else [round(x, 4) for x in c.lab],
                hex=c.hex,
                out_of_srgb_gamut=c.out_of_srgb_gamut,
                xy=None if c.xy is None else [round(x, 6) for x in c.xy],
                spectrum=(
                    c.reflectance.round(6).tolist()
                    if body.include_spectra and c.reflectance is not None
                    else None
                ),
            )
            for i, c in enumerate(cells)
        ],
    )


@router.get("/gamut", response_model=GamutResponse)
async def gamut(
    session: SessionDep,
    request: Request,
    pool: str | None = Query(None, description="Comma-separated paint ids; default = loaded"),
    max_paints: int | None = Query(None, ge=1, le=8),
) -> GamutResponse:
    """a*b* boundary (max chroma per 10° hue bin) at L* slices every 10 units, for the active
    model. ``GET /models/{version}/gamut`` does the same for any model version."""
    ids = [p.strip() for p in pool.split(",") if p.strip()] if pool else None
    model, fm = pool_model(session, ids)
    k = max_paints or load_settings(session).max_paints
    g = await run_compute(request.app, gamut_for, model, k, fm.version)
    return gamut_response(model, fm, g, k)
