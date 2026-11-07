"""Subset screening: batched Levenberg-Marquardt on Lab over many paint subsets at once.

Fractions are parameterised as ``c = lo + (1 - k*lo) * softmax(z)`` so every member of a subset
keeps at least ``lo`` (the minimum fraction) and the fractions always sum to 1. All subsets of
the same size are solved together with NumPy batch linear algebra, which is what makes an
exhaustive search over thousands of subsets fast enough.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.km import inverse_saunderson, ks_from_r
from paintmixer.colorsci.types import FloatArray, IntArray
from paintmixer.solver.model import PoolModel


@dataclass
class Screened:
    idx: IntArray  # (m, k)
    c: FloatArray  # (m, k)
    lab: FloatArray  # (m, 3)
    de: FloatArray  # (m,) dE2000 at the Lab optimum


def _softmax(z: FloatArray) -> FloatArray:
    e = np.exp(z - z.max(axis=1, keepdims=True))
    out: FloatArray = e / e.sum(axis=1, keepdims=True)
    return out


def to_c(z: FloatArray, lo: float) -> FloatArray:
    k = z.shape[1]
    out: FloatArray = lo + (1.0 - k * lo) * _softmax(z)
    return out


def to_z(c: FloatArray, lo: float) -> FloatArray:
    k = c.shape[1]
    s = (np.clip(c, lo, None) - lo) / max(1.0 - k * lo, 1e-9)
    s = np.maximum(s, 1e-4)
    s = s / s.sum(axis=1, keepdims=True)
    out: FloatArray = np.log(s)
    return out


def nnls_init(
    model: PoolModel, idx: IntArray, target_spectrum: FloatArray, lo: float
) -> FloatArray:
    """Initial fractions from NNLS in K/S space: ``sum c_i (K_i - ks_t S_i) ≈ 0``, ``sum c = 1``."""
    ks_t = ks_from_r(inverse_saunderson(target_spectrum, model.km.k1, model.km.k2))
    A_all = model.km.K - ks_t[None, :] * model.km.S  # (n, 31)
    scale = 1.0 / np.maximum(np.abs(A_all).max(axis=0), 1e-6)  # band balance
    A_all = A_all * scale
    m, k = idx.shape
    out = np.empty((m, k))
    lam = 10.0
    for i in range(m):
        A = np.vstack([A_all[idx[i]].T, lam * np.ones((1, k))])
        b = np.zeros(A.shape[0])
        b[-1] = lam
        sol, _ = nnls(A, b)
        s = sol.sum()
        out[i] = sol / s if s > 0 else 1.0 / k
    return np.maximum(out, lo)


def lm_batch(
    model: PoolModel,
    idx: IntArray,
    target_lab: FloatArray,
    z0: FloatArray,
    lo: float,
    iters: int = 30,
) -> tuple[FloatArray, FloatArray]:
    """Minimise ||Lab(c) - target||^2 for each row of ``idx``. Returns (c, lab)."""
    m, k = idx.shape
    z = z0.copy()
    mu = np.full(m, 1e-2)
    c = to_c(z, lo)
    lab = model.lab(idx, c)
    cost = np.sum((lab - target_lab) ** 2, axis=1)
    if k == 1:
        return c, lab
    eye = np.eye(k)[None]
    span = 1.0 - k * lo
    for _ in range(iters):
        lab, jc = model.lab_jac(idx, c)
        r = lab - target_lab
        s = (c - lo) / span
        dcdz = span * (s[:, :, None] * eye - s[:, :, None] * s[:, None, :])
        jz = jc @ dcdz  # (m, 3, k)
        a = np.transpose(jz, (0, 2, 1)) @ jz
        g = np.einsum("mik,mi->mk", jz, r)
        diag = np.einsum("mkk->mk", a) + 1e-9
        a_d = a + (mu[:, None] * diag)[:, :, None] * eye + 1e-9 * eye
        step = -np.linalg.solve(a_d, g[:, :, None])[:, :, 0]
        step = np.clip(step, -4.0, 4.0)
        z_new = z + step
        c_new = to_c(z_new, lo)
        lab_new = model.lab(idx, c_new)
        cost_new = np.sum((lab_new - target_lab) ** 2, axis=1)
        ok = cost_new < cost
        z = np.where(ok[:, None], z_new, z)
        c = np.where(ok[:, None], c_new, c)
        cost = np.where(ok, cost_new, cost)
        mu = np.where(ok, mu / 3.0, mu * 4.0)
        mu = np.clip(mu, 1e-7, 1e7)
    lab = model.lab(idx, c)
    return c, lab


def screen(
    model: PoolModel,
    subsets: Sequence[tuple[int, ...]],
    target_lab: FloatArray,
    lo: float,
    target_spectrum: FloatArray | None = None,
    iters: int = 30,
) -> Screened:
    """Optimise every subset (grouped by size) from two starts; keep the better per subset."""
    idx_out, c_out, lab_out = [], [], []
    by_k: dict[int, list[tuple[int, ...]]] = {}
    for s in subsets:
        if len(s) * lo <= 1.0 + 1e-12:
            by_k.setdefault(len(s), []).append(s)
    for k in sorted(by_k):
        idx = np.array(by_k[k], dtype=np.int64)
        starts = [np.zeros((len(idx), k))]
        if target_spectrum is not None and k > 1:
            starts.append(to_z(nnls_init(model, idx, target_spectrum, lo), lo))
        best_c, best_lab = lm_batch(model, idx, target_lab, starts[0], lo, iters)
        best_cost = np.sum((best_lab - target_lab) ** 2, axis=1)
        for z0 in starts[1:]:
            c, lab = lm_batch(model, idx, target_lab, z0, lo, iters)
            cost = np.sum((lab - target_lab) ** 2, axis=1)
            better = cost < best_cost
            best_c = np.where(better[:, None], c, best_c)
            best_lab = np.where(better[:, None], lab, best_lab)
            best_cost = np.where(better, cost, best_cost)
        idx_out.append(idx)
        c_out.append(best_c)
        lab_out.append(best_lab)
    if not idx_out:
        empty = np.zeros((0, 0))
        return Screened(empty.astype(np.int64), empty, np.zeros((0, 3)), np.zeros(0))
    # ragged by k: pad idx/c to max k with -1 / 0 so callers can index row-wise
    kmax = max(i.shape[1] for i in idx_out)
    idx_p = np.concatenate(
        [np.pad(i, ((0, 0), (0, kmax - i.shape[1])), constant_values=-1) for i in idx_out]
    )
    c_p = np.concatenate([np.pad(c, ((0, 0), (0, kmax - c.shape[1]))) for c in c_out])
    lab = np.concatenate(lab_out)
    de = delta_e_2000(lab, target_lab[None, :])
    return Screened(idx_p, c_p, lab, de)


def all_subsets(
    n: int,
    max_paints: int,
    required: Iterable[int] = (),
    excluded: Iterable[int] = (),
) -> list[tuple[int, ...]]:
    req = set(required)
    exc = set(excluded)
    pool = [i for i in range(n) if i not in exc]
    out: list[tuple[int, ...]] = []
    for k in range(1, max_paints + 1):
        for s in itertools.combinations(pool, k):
            if req <= set(s):
                out.append(s)
    return out


def staged_subsets(
    model: PoolModel,
    target_lab: FloatArray,
    max_paints: int,
    lo: float,
    required: Sequence[int] = (),
    excluded: Sequence[int] = (),
    target_spectrum: FloatArray | None = None,
    keep: int = 40,
    min_prefilter: int = 8,
) -> tuple[list[tuple[int, ...]], int]:
    """Greedy forward selection + swap refinement for large pools.

    Returns the best ``keep`` subsets found (by screened dE) and how many subsets were screened.
    """
    from paintmixer.colorsci.convert import lab_to_lch
    from paintmixer.domain import PaintRole

    n = model.n
    exc = set(excluded)
    cand = [i for i in range(n) if i not in exc]
    # hue pre-filter on 20 % tints with white (or masstones when no white is present)
    whites = [i for i in cand if model.paints[i].role == PaintRole.WHITE]
    chrom = [i for i in cand if model.paints[i].role == PaintRole.CHROMATIC]
    t_lch = lab_to_lch(target_lab)
    # darks and greys are mixed from complementary paints, so only filter clear chromatic targets
    if chrom and t_lch[1] > 15.0 and t_lch[0] > 25.0:
        if whites:
            idx = np.array([[i, whites[0]] for i in chrom])
            hue_lab = model.lab(idx, np.tile([0.2, 0.8], (len(chrom), 1)))
        else:
            hue_lab = model.lab(np.array(chrom)[:, None], np.ones((len(chrom), 1)))
        h = lab_to_lch(hue_lab)[:, 2]
        dh = np.abs((h - t_lch[2] + 180.0) % 360.0 - 180.0)
        keep_chrom = [chrom[i] for i in np.argsort(dh) if dh[i] <= 120.0]
        need = max(0, min_prefilter - (len(cand) - len(chrom)))
        keep_chrom = sorted(set(keep_chrom) | {chrom[i] for i in np.argsort(dh)[: max(need, 3)]})
        cand = [i for i in cand if i not in chrom or i in keep_chrom]

    seen: dict[tuple[int, ...], float] = {}

    def evaluate(subs: list[tuple[int, ...]]) -> None:
        subs = [s for s in {tuple(sorted(x)) for x in subs} if s not in seen]
        if not subs:
            return
        sc = screen(model, subs, target_lab, lo, target_spectrum)
        for row in range(len(sc.de)):
            key = tuple(int(i) for i in sc.idx[row] if i >= 0)
            seen[key] = float(sc.de[row])

    req = tuple(sorted(set(required)))
    base_sets: list[tuple[int, ...]] = [req] if req else [()]
    # greedy forward selection with a small beam
    beam = 4
    frontier = base_sets
    for _size in range(len(req) + 1, max_paints + 1):
        ext = [tuple(sorted((*b, i))) for b in frontier for i in cand if i not in b]
        evaluate(ext)
        ranked = sorted({e for e in ext if e in seen}, key=lambda s: seen[s])
        frontier = ranked[:beam]
        if not frontier:
            break
    # swap refinement of the best subsets of each size
    for _round in range(3):
        improved = False
        sizes = sorted({len(s) for s in seen})
        for size in sizes:
            best = sorted((s for s in seen if len(s) == size), key=lambda s: seen[s])[:2]
            for b in best:
                swaps = [
                    tuple(sorted((*[x for x in b if x != out_], in_)))
                    for out_ in b
                    if out_ not in req
                    for in_ in cand
                    if in_ not in b
                ]
                before = seen[b]
                evaluate(swaps)
                if any(seen.get(s, np.inf) < before - 1e-6 for s in swaps):
                    improved = True
        if not improved:
            break
    ranked = sorted(seen, key=lambda s: seen[s])
    return ranked[:keep], len(seen)
