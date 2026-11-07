"""Per-subset refinement on the full objective, quantisation and per-recipe diagnostics."""

from __future__ import annotations

import warnings as _warnings
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from paintmixer.colorsci.convert import xyz_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.spectral import Illuminant, white_point
from paintmixer.colorsci.types import FloatArray, IntArray
from paintmixer.solver.model import PoolModel

META_ILLUMINANTS = (Illuminant.A, Illuminant.F11)
_SMOOTH = 0.05


@dataclass(frozen=True)
class Weights:
    """Objective weights (dE2000 units per unit of each term)."""

    de: float = 1.0
    n_paints: float = 0.05  # per paint
    cost: float = 0.5  # per (currency / ml of mixture)
    metamerism: float = 0.05  # per dE2000 of metamerism (mean of A and F11)
    min_fraction_penalty: float = 50.0


@dataclass
class Objective:
    model: PoolModel
    target_lab: FloatArray
    reference_spectrum: FloatArray  # measured or reconstructed target spectrum
    weights: Weights
    min_fraction: float

    def __post_init__(self) -> None:
        self._ref_lab = {
            ill: xyz_to_lab(self.reference_spectrum @ self.model.W(ill).T, white_point(ill))
            for ill in META_ILLUMINANTS
        }

    def terms(self, idx: IntArray, c: FloatArray) -> dict[str, FloatArray]:
        """All objective terms for a batch ``idx (m,k)``, ``c (m,k)``."""
        R = self.model.reflectance(idx, c)
        m = R.shape[0]
        labs = [xyz_to_lab(R @ self.model.W(Illuminant.D65).T, white_point(Illuminant.D65))]
        refs = [np.broadcast_to(self.target_lab, (m, 3))]
        for ill in META_ILLUMINANTS:
            labs.append(xyz_to_lab(R @ self.model.W(ill).T, white_point(ill)))
            refs.append(np.broadcast_to(self._ref_lab[ill], (m, 3)))
        all_de = delta_e_2000(np.concatenate(labs), np.concatenate(refs)).reshape(-1, m)
        lab = labs[0]
        de = all_de[0]
        meta_a = all_de[1:].T
        # smooth near zero so gradient-based refinement is well behaved (dE is a cone at 0)
        de_smooth = np.sqrt(de * de + _SMOOTH**2) - _SMOOTH
        cost = (c * self.model.cost[idx]).sum(axis=1) / np.maximum(c.sum(axis=1), 1e-12)
        k = (c > 0).sum(axis=1).astype(np.float64)
        short = np.clip(self.min_fraction - c, 0.0, None)
        short = np.where(c > 0, short, 0.0).sum(axis=1)
        w = self.weights
        total = (
            w.de * de_smooth
            + w.n_paints * k
            + w.cost * cost
            + w.metamerism * meta_a.mean(axis=1)
            + w.min_fraction_penalty * short
        )
        return {
            "total": total,
            "de": de,
            "lab": lab,
            "R": R,
            "meta": meta_a,
            "cost": cost,
        }

    def value(self, idx: IntArray, c: FloatArray) -> float:
        return float(self.terms(idx[None, :], c[None, :])["total"][0])

    def values(self, idx: IntArray, cs: FloatArray) -> FloatArray:
        """Objective for many fraction vectors ``cs (m, k)`` of the same subset."""
        return self.terms(np.tile(idx, (cs.shape[0], 1)), cs)["total"]

    def value_and_grad(
        self, idx: IntArray, c: FloatArray, h: float = 1e-6
    ) -> tuple[float, FloatArray]:
        """Objective and forward-difference gradient from one batched evaluation."""
        k = c.size
        pts = np.vstack([c, c + h * np.eye(k)])
        v = self.values(idx, pts)
        return float(v[0]), (v[1:] - v[0]) / h


def refine_subset(
    obj: Objective, idx: IntArray, c0: FloatArray, rng: np.random.Generator, n_starts: int = 3
) -> tuple[FloatArray, float]:
    """Multi-start SLSQP on the simplex with ``c_i >= min_fraction``."""
    k = idx.size
    lo = obj.min_fraction
    if k == 1:
        c = np.ones(1)
        return c, obj.value(idx, c)
    starts = [c0]
    for _ in range(n_starts - 1):
        d = rng.dirichlet(np.ones(k))
        starts.append(np.clip(0.7 * c0 + 0.3 * d, lo, None))
    best_c, best_v = c0, obj.value(idx, c0)
    cons = ({"type": "eq", "fun": lambda x: np.sum(x) - 1.0, "jac": lambda x: np.ones_like(x)},)
    for s in starts:
        s = s / s.sum()
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            res = minimize(
                lambda x: obj.value_and_grad(idx, x),
                s,
                jac=True,
                method="SLSQP",
                bounds=[(lo, 1.0)] * k,
                constraints=cons,
                options={"maxiter": 60, "ftol": 1e-8},
            )
        x = np.clip(res.x, lo, 1.0)
        x = x / x.sum()
        v = obj.value(idx, x)
        if v < best_v - 1e-12:
            best_c, best_v = x, v
    return best_c, best_v


@dataclass
class Quantised:
    volumes_ml: FloatArray
    fractions: FloatArray
    value: float
    steps: int


def quantise(
    obj: Objective,
    idx: IntArray,
    c: FloatArray,
    batch_ml: float,
    resolution_ml: float,
    min_dose_ml: FloatArray,
    max_iter: int = 200,
) -> Quantised:
    """Round volumes to the dispenser resolution and minimum dose, then local integer search.

    Moves: +-1 step on one paint (total kept within +-k steps of the batch) and transfers of one
    step between two paints. Accept the best improving move until none improves.
    """
    r = resolution_ml
    k = idx.size
    min_steps = np.maximum(np.ceil(min_dose_ml / r - 1e-9), 1).astype(np.int64)
    steps = np.maximum(np.round(c * batch_ml / r).astype(np.int64), min_steps)
    target_total = round(batch_ml / r)

    def val(st: np.ndarray) -> float:
        return obj.value(idx, st / st.sum())

    best = val(steps)
    n_moves = 0
    for _ in range(max_iter):
        cands = []
        for i in range(k):
            for d in (-1, 1):
                s = steps.copy()
                s[i] += d
                if s[i] >= min_steps[i] and abs(int(s.sum()) - target_total) <= k:
                    cands.append(s)
            for j in range(k):
                if i != j:
                    s = steps.copy()
                    s[i] += 1
                    s[j] -= 1
                    if s[j] >= min_steps[j]:
                        cands.append(s)
        if not cands:
            break
        arr = np.array(cands, dtype=np.float64)
        vals = obj.values(idx, arr / arr.sum(axis=1, keepdims=True))
        j = int(np.argmin(vals))
        if vals[j] < best - 1e-9:
            best, steps = vals[j], cands[j]
            n_moves += 1
        else:
            break
    vol = steps.astype(np.float64) * r
    return Quantised(vol, vol / vol.sum(), best, n_moves)


def dose_sensitivity(model: PoolModel, idx: IntArray, c: FloatArray, pct: float = 1.0) -> float:
    """Worst-case dE2000 when any one paint is over-dosed by ``pct`` % of the batch volume."""
    base = model.lab(idx[None, :], c[None, :])
    pert = np.tile(c, (idx.size, 1)) + np.eye(idx.size) * (pct / 100.0)
    pert = pert / pert.sum(axis=1, keepdims=True)
    lab = model.lab(np.tile(idx, (idx.size, 1)), pert)
    return float(delta_e_2000(lab, base).max())
