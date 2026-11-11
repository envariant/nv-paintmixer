"""Recipe solver: target colour + paint pool -> ranked, quantised mixing recipes.

Pipeline (see PLAN.md):

1. gamut pre-check;
2. candidate subsets: exhaustive up to ``max_paints`` when the pool has <= 14 paints, otherwise
   hue pre-filter + greedy forward selection + swap refinement;
3. every subset is screened with a batched Levenberg-Marquardt on Lab (starts: equal fractions
   and NNLS in K/S space on the target spectrum, measured or reconstructed);
4. the best subsets are refined with multi-start SLSQP on
   ``dE2000 + w_n*n + w_cost*cost + w_meta*metamerism + min-fraction penalty``;
5. recipes are quantised to dispenser resolution and minimum dose and re-optimised;
6. metamerism under the checked lights and dose sensitivity are reported; out-of-gamut targets
   return the nearest achievable colour with a warning;
7. the returned candidates differ in kind: the closest, and the fewest paints and the cheapest
   within reach of the closest, each tagged with its role (:func:`select_candidates`), then the
   rest by objective.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from paintmixer.calibration.accuracy import mix_uncertainty
from paintmixer.colorsci.convert import (
    lab_to_srgb,
    reflectance_to_lab,
    reflectance_to_srgb,
    srgb_to_hex,
)
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.recovery import lab_to_reflectance
from paintmixer.colorsci.spectral import Illuminant
from paintmixer.colorsci.types import FloatArray
from paintmixer.domain import PaintRole
from paintmixer.solver.gamut import Gamut, compute_gamut
from paintmixer.solver.model import PoolModel
from paintmixer.solver.refine import (
    Objective,
    Weights,
    dose_sensitivity,
    quantise,
    refine_subset,
)
from paintmixer.solver.search import all_subsets, screen, staged_subsets

EXHAUSTIVE_MAX_POOL = 14


@dataclass
class SolveOptions:
    max_paints: int = 5
    min_fraction: float = 0.02
    include_white: bool | None = None  # None = allowed, True = required, False = excluded
    illuminant: Illuminant = Illuminant.D65
    check_illuminants: tuple[Illuminant, ...] = (Illuminant.A, Illuminant.F11)
    batch_volume_ml: float = 100.0
    resolution_ml: float = 0.05
    weights: Weights = field(default_factory=Weights)
    top_n: int = 5
    refine_top: int = 12
    seed: int = 0
    search: str = "auto"  # auto | exhaustive | staged
    gamut_check: bool = True
    out_of_gamut_de: float = 1.0
    n_jobs: int = 1
    # "close enough" band for the role picks: dE2000 <= max(1.5 x closest, this)
    accept_tolerance_de: float = 1.0
    # per-paint calibration error (dE2000, see calibration.accuracy) -> Candidate.uncertainty_de
    paint_error_de: dict[str, float] | None = None


@dataclass
class Target:
    lab: FloatArray
    spectrum: FloatArray | None = None
    name: str = ""
    source: str = "lab"


@dataclass
class Candidate:
    rank: int
    paint_ids: list[str]
    fractions: list[float]  # continuous optimum
    fractions_quantised: list[float]
    volumes_ml: list[float]
    masses_g: list[float]
    predicted_spectrum: list[float]
    predicted_lab: list[float]
    predicted_hex: str
    de2000: float  # after quantisation
    de2000_continuous: float
    cost: float  # currency for the batch
    cost_per_ml: float
    metamerism: dict[str, float]  # dE2000 vs reference under each illuminant
    dose_sensitivity: float  # dE2000 per 1 % overdose of any one paint
    objective: float
    warnings: list[str]
    tags: list[str] = field(default_factory=list)  # roles: closest, fewest paints, ...
    uncertainty_de: float | None = None  # expected spread of the predicted dE2000

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class SolveResult:
    target_lab: list[float]
    target_hex: str
    target_in_srgb_gamut: bool
    reference_spectrum: list[float]
    reference_spectrum_source: str  # measured | reconstructed
    candidates: list[Candidate]
    in_gamut: bool | None
    nearest_de: float
    warnings: list[str]
    search: str
    n_subsets: int
    duration_s: float
    gamut_margin_de: float | None = None  # signed dE2000 to the gamut edge; < 0 iff out of gamut


def pool_warnings(model: PoolModel) -> list[str]:
    out = []
    if not model.role_mask(PaintRole.WHITE).any():
        out.append(
            "No white paint in the pool: pale colours are unreachable (only white adds scattering)."
        )
    if not model.role_mask(PaintRole.BLACK).any():
        out.append("No black paint in the pool: deep darks and clean neutrals are limited.")
    if int(model.role_mask(PaintRole.CHROMATIC).sum()) < 3:
        out.append("Fewer than 3 chromatic paints in the pool: the hue range is limited.")
    return out


_GAMUT_CACHE: dict[tuple[Any, ...], Gamut] = {}


def gamut_for(model: PoolModel, max_paints: int = 5, cache_key: Any = None) -> Gamut:
    key = (cache_key, tuple(model.ids), max_paints) if cache_key is not None else None
    if key is not None and key in _GAMUT_CACHE:
        return _GAMUT_CACHE[key]
    g = compute_gamut(model, max_paints)
    if key is not None:
        if len(_GAMUT_CACHE) > 32:
            _GAMUT_CACHE.clear()
        _GAMUT_CACHE[key] = g
    return g


def solve(
    model: PoolModel,
    target: Target,
    options: SolveOptions | None = None,
    gamut_cache_key: Any = None,
) -> SolveResult:
    opts = options or SolveOptions()
    t0 = time.perf_counter()
    rng = np.random.default_rng(opts.seed)
    warnings = pool_warnings(model)
    target_lab = np.asarray(target.lab, dtype=np.float64)
    if target.spectrum is not None:
        ref = np.asarray(target.spectrum, dtype=np.float64)
        ref_source = "measured"
        if opts.illuminant != Illuminant.D65:
            target_lab = reflectance_to_lab(ref, opts.illuminant)
    else:
        ref = lab_to_reflectance(target_lab)
        ref_source = "reconstructed"
    ill = opts.illuminant if target.spectrum is not None else Illuminant.D65
    if opts.illuminant != Illuminant.D65 and target.spectrum is None:
        warnings.append("Target has no spectrum: matching under D65; illuminant setting ignored.")

    in_gamut: bool | None = None
    g: Gamut | None = None
    if opts.gamut_check:
        g = gamut_for(model, opts.max_paints, gamut_cache_key)
        in_gamut = g.contains(target_lab)
        if not in_gamut:
            warnings.append("Target appears to be outside the gamut of the selected paints.")

    whites = [i for i, p in enumerate(model.paints) if p.role == PaintRole.WHITE]
    excluded: list[int] = []
    if opts.include_white is False:
        excluded = whites
    max_k = min(opts.max_paints, model.n - len(excluded))
    mode = opts.search
    if mode == "auto":
        mode = "exhaustive" if model.n <= EXHAUSTIVE_MAX_POOL else "staged"

    if opts.include_white is True:
        if not whites:
            warnings.append("include_white requested but the pool has no white.")
            subsets = all_subsets(model.n, max_k, excluded=excluded)
        else:
            subsets = []
            for w in whites:
                subsets += all_subsets(model.n, max_k, required=[w], excluded=excluded)
            subsets = sorted(set(subsets), key=lambda s: (len(s), s))
    else:
        subsets = all_subsets(model.n, max_k, excluded=excluded)

    if mode == "staged":
        req = [whites[0]] if (opts.include_white is True and whites) else []
        top_subsets, n_eval = staged_subsets(
            model, target_lab, max_k, opts.min_fraction, req, excluded, ref, ill=ill
        )
        sc = screen(model, top_subsets, target_lab, opts.min_fraction, ref, ill=ill)
    else:
        sc = screen(model, subsets, target_lab, opts.min_fraction, ref, ill=ill)
        n_eval = len(subsets)

    obj = Objective(
        model,
        target_lab,
        ref,
        opts.weights,
        opts.min_fraction,
        ill,
        check_illuminants=opts.check_illuminants,
    )
    # rank screened subsets by the full objective at their Lab optimum
    pre = []
    sizes = (sc.idx >= 0).sum(axis=1)
    for k in np.unique(sizes):
        rows = np.flatnonzero(sizes == k)
        idx_k = sc.idx[rows, :k]
        c_k = sc.c[rows, :k]
        vals = obj.terms(idx_k, c_k)["total"]
        pre += [(float(vals[j]), idx_k[j], c_k[j]) for j in range(rows.size)]
    pre.sort(key=lambda t: (t[0], tuple(t[1])))
    picked = list(pre[: max(opts.refine_top, opts.top_n)])
    keys = {tuple(int(i) for i in t[1]) for t in picked}
    for t in _best_per_size(pre):  # so "fewest paints" has a refined contender
        if tuple(int(i) for i in t[1]) not in keys:
            keys.add(tuple(int(i) for i in t[1]))
            picked.append(t)
    refined = []
    for _v, idx, c in picked:
        c_best, v = refine_subset(obj, idx, c, rng)
        refined.append((v, idx, c_best))
    refined.sort(key=lambda t: (t[0], tuple(t[1])))

    cands: list[Candidate] = []
    min_dose = np.array([p.min_dose_ml for p in model.paints])
    density = np.array([p.density_g_per_ml for p in model.paints])
    dose_error_pct = 100.0 * opts.resolution_ml / opts.batch_volume_ml
    errors = opts.paint_error_de
    for _v_cont, idx, c in refined:
        q = quantise(obj, idx, c, opts.batch_volume_ml, opts.resolution_ml, min_dose[idx])
        terms = obj.terms(idx[None, :], q.fractions[None, :])
        de_q = float(terms["de"][0])
        de_c = float(obj.terms(idx[None, :], c[None, :])["de"][0])
        R = terms["R"][0]
        lab = terms["lab"][0]  # under the matching illuminant
        srgb = reflectance_to_srgb(R)  # swatches are always rendered under D65
        meta = {x.value: float(terms["meta"][0, j]) for j, x in enumerate(obj.meta_illuminants)}
        cw: list[str] = []
        if de_q - de_c > 0.3:
            cw.append(
                f"Quantisation to {opts.resolution_ml:g} ml raises dE2000 from {de_c:.2f} to "
                f"{de_q:.2f}; use a larger batch or finer dispenser."
            )
        if de_q > opts.out_of_gamut_de:
            cw.append(
                f"Best achievable dE2000 is {de_q:.2f}: the target is outside what these paints "
                "can mix; this is the nearest achievable colour."
            )
        if max(meta.values()) > 2.0:
            cw.append(
                f"Metamerism: the match shifts by up to {max(meta.values()):.1f} dE2000 under "
                f"{'/'.join(meta)} ({ref_source} target spectrum)."
            )
        sens = dose_sensitivity(model, idx, q.fractions, ill=ill)
        if sens > 2.0:
            cw.append(f"Dose-sensitive recipe: 1 % overdose of one paint moves it {sens:.1f} dE.")
        vols = q.volumes_ml
        cost_per_ml = float(np.dot(q.fractions, model.cost[idx]))
        ids = [model.ids[i] for i in idx]
        unc = None
        if errors is not None and all(p in errors for p in ids):
            unc = mix_uncertainty(q.fractions, [errors[p] for p in ids], sens, dose_error_pct)
        cands.append(
            Candidate(
                rank=len(cands) + 1,
                paint_ids=ids,
                fractions=[float(x) for x in c],
                fractions_quantised=[float(x) for x in q.fractions],
                volumes_ml=[float(x) for x in vols],
                masses_g=[float(x) for x in vols * density[idx]],
                predicted_spectrum=[float(x) for x in R],
                predicted_lab=[float(x) for x in lab],
                predicted_hex=srgb_to_hex(srgb.rgb),
                de2000=de_q,
                de2000_continuous=de_c,
                cost=float(cost_per_ml * vols.sum()),
                cost_per_ml=cost_per_ml,
                metamerism=meta,
                dose_sensitivity=sens,
                objective=float(q.value),
                warnings=cw,
                uncertainty_de=unc,
            )
        )
    # re-rank after quantisation (stable on ties), then keep a varied top_n
    cands.sort(key=lambda x: (x.objective, x.paint_ids))
    cands = select_candidates(cands, opts.top_n, opts.accept_tolerance_de)
    for i, cand in enumerate(cands):
        cand.rank = i + 1
    nearest = cands[0].de2000 if cands else float("inf")
    if cands and nearest > opts.out_of_gamut_de:
        warnings.append(
            f"Out of gamut: nearest achievable colour is dE2000 {nearest:.2f} from the target."
        )
        in_gamut = False
    margin = _gamut_margin(g, target_lab, in_gamut, nearest)
    t_srgb = lab_to_srgb(target_lab)
    return SolveResult(
        target_lab=[float(x) for x in target_lab],
        target_hex=srgb_to_hex(t_srgb.rgb),
        target_in_srgb_gamut=not bool(t_srgb.out_of_gamut),
        reference_spectrum=[float(x) for x in ref],
        reference_spectrum_source=ref_source,
        candidates=cands,
        in_gamut=in_gamut,
        nearest_de=float(nearest),
        warnings=warnings,
        search=mode,
        n_subsets=n_eval,
        duration_s=time.perf_counter() - t0,
        gamut_margin_de=margin,
    )


def _best_per_size(pre: Sequence[tuple[float, Any, Any]]) -> list[tuple[float, Any, Any]]:
    """The best screened subset (objective order) of each size."""
    out = []
    sizes: set[int] = set()
    for t in pre:
        if len(t[1]) not in sizes:
            sizes.add(len(t[1]))
            out.append(t)
    return out


def select_candidates(
    cands: Sequence[Candidate],
    top_n: int,
    accept_tolerance_de: float,
) -> list[Candidate]:
    """Pick ``top_n`` candidates that differ in kind, tagging each with the roles it wins.

    ``cands`` is in objective order. Roles, in priority order: ``closest`` (lowest dE2000);
    ``fewest paints`` and ``cheapest`` (per ml), both among candidates within
    max(1.5 x the closest dE2000, ``accept_tolerance_de``). ``cheapest`` is skipped
    when every candidate in reach costs the same (e.g. no paint costs set). One candidate can
    win several roles. Role winners come first, the rest is filled in objective order, and the
    result is returned in objective order.
    """
    for c in cands:
        c.tags = []
    if not cands:
        return []
    closest = min(cands, key=lambda c: (c.de2000, c.objective))
    band = max(1.5 * closest.de2000, accept_tolerance_de)
    near = [c for c in cands if c.de2000 <= band]
    winners: list[tuple[str, Candidate]] = [
        ("closest", closest),
        ("fewest paints", min(near, key=lambda c: (len(c.paint_ids), c.de2000))),
    ]
    if len({round(c.cost_per_ml, 9) for c in near}) > 1:
        winners.append(("cheapest", min(near, key=lambda c: (c.cost_per_ml, c.de2000))))
    chosen: list[int] = []  # id() of the picked candidates, in pick order
    for tag, c in winners:
        if id(c) in chosen or len(chosen) < top_n:
            c.tags.append(tag)
            if id(c) not in chosen:
                chosen.append(id(c))
    for c in cands:
        if len(chosen) >= top_n:
            break
        if id(c) not in chosen:
            chosen.append(id(c))
    keep = set(chosen)
    return [c for c in cands if id(c) in keep]


def _gamut_margin(
    g: Gamut | None, target_lab: FloatArray, in_gamut: bool | None, nearest: float
) -> float | None:
    """Signed distance to the gamut edge, made consistent with ``in_gamut``: the gamut is a
    sampled estimate and the pre-check allows 2 dE2000 at the edge, while ``in_gamut`` also
    turns False when the solver cannot get within ``out_of_gamut_de``. Inside but within the
    pre-check's tolerance reads 0; reported out of gamut although the sampled edge encloses the
    target reads minus the nearest achievable dE2000."""
    if in_gamut is None:
        return None
    margin = g.margin_de(target_lab) if g is not None else None
    if in_gamut:
        return None if margin is None else max(margin, 0.0)
    if margin is None or margin >= 0:
        return -max(nearest, 0.01) if math.isfinite(nearest) else None
    return margin


def predict(model: PoolModel, paint_ids: Sequence[str], fractions: Sequence[float]) -> FloatArray:
    idx = np.array([model.ids.index(p) for p in paint_ids], dtype=np.int64)
    c = np.asarray(fractions, dtype=np.float64)
    c = c / c.sum()
    out: FloatArray = model.reflectance(idx[None, :], c[None, :])[0]
    return out


def delta_e(lab1: Sequence[float], lab2: Sequence[float]) -> float:
    return float(delta_e_2000(np.asarray(lab1), np.asarray(lab2)))
