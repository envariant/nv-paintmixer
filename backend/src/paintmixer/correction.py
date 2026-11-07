"""Closed-loop recipe correction from a measured mix.

After a mix is measured, the Lab residual ``r = target - measured`` is assumed to come from a
locally constant model bias, so the correction solves ``J Δc ≈ r`` with ``J = dLab/dc`` of the
fitted model at the current recipe (damped Gauss-Newton / Levenberg-Marquardt on the simplex
tangent space, ``sum Δc = 0``), with a step-length cap. Because paint cannot be removed from a
batch, the new recipe is also expressed as the smallest set of *additions* to what is already in
the cup.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.types import FloatArray, IntArray
from paintmixer.solver.model import PoolModel


@dataclass
class CorrectionStep:
    fractions: FloatArray  # new recipe (sums to 1)
    delta: FloatArray
    predicted_lab: FloatArray  # model prediction of the new recipe, bias-corrected
    expected_de: float


def correction_step(
    model: PoolModel,
    idx: IntArray,
    c: FloatArray,
    target_lab: FloatArray,
    measured_lab: FloatArray,
    *,
    damping: float = 1e-3,
    max_step: float = 0.15,
    min_fraction: float = 0.0,
) -> CorrectionStep:
    c = np.asarray(c, dtype=np.float64) / np.sum(c)
    lab_pred, jac = model.lab_jac(idx[None, :], c[None, :])
    J = jac[0]  # (3, k)
    bias = measured_lab - lab_pred[0]
    k = c.size
    # orthonormal basis of {d : sum d = 0}
    q, _ = np.linalg.qr(np.vstack([np.ones(k), np.eye(k)[:-1]]).T)
    N = q[:, 1:]
    r = target_lab - measured_lab
    JN = J @ N
    a = JN.T @ JN
    z = np.linalg.solve(
        a + damping * (np.trace(a) / max(k - 1, 1) + 1e-9) * np.eye(k - 1), JN.T @ r
    )
    d = N @ z
    norm = np.abs(d).max()
    if norm > max_step:
        d *= max_step / norm
    new = np.clip(c + d, min_fraction, None)
    new /= new.sum()
    lab_new = model.lab(idx[None, :], new[None, :])[0] + bias
    return CorrectionStep(new, new - c, lab_new, float(delta_e_2000(lab_new, target_lab)))


def additions_for(current_ml: FloatArray, new_fractions: FloatArray) -> tuple[FloatArray, float]:
    """Smallest additions so the cup contents have ``new_fractions``. Returns (additions, total)."""
    f = np.maximum(new_fractions, 1e-12)
    total = float(np.max(current_ml / f))
    total = max(total, float(current_ml.sum()))
    adds = np.maximum(total * f - current_ml, 0.0)
    return adds, float(current_ml.sum() + adds.sum())


@dataclass
class LoopIteration:
    iteration: int
    fractions: list[float]
    dispensed_ml: list[float]  # cumulative contents of the cup
    measured_lab: list[float]
    de: float
    additions_ml: list[float] = field(default_factory=list)


@dataclass
class LoopResult:
    converged: bool
    iterations: list[LoopIteration]
    final_de: float
    message: str


def run_closed_loop(
    model: PoolModel,
    paint_ids: Sequence[str],
    fractions: Sequence[float],
    target_lab: FloatArray,
    batch_ml: float,
    dispense: Callable[[FloatArray], FloatArray],
    measure: Callable[[FloatArray], FloatArray],
    *,
    tolerance_de: float = 0.5,
    max_iter: int = 5,
    damping: float = 1e-3,
    mode: str = "additions",
) -> LoopResult:
    """Dispense -> measure -> correct until within ``tolerance_de`` or ``max_iter`` corrections.

    ``dispense(volumes)`` returns actually delivered volumes; ``measure(cup_volumes)`` returns the
    measured Lab of the cup contents. In ``additions`` mode corrections are added to the cup; in
    ``remix`` mode each iteration starts a fresh batch with the corrected recipe.
    """
    idx = np.array([model.ids.index(p) for p in paint_ids], dtype=np.int64)
    c = np.asarray(fractions, dtype=np.float64)
    c = c / c.sum()
    cup = dispense(c * batch_ml)
    its: list[LoopIteration] = []
    for it in range(max_iter + 1):
        lab = measure(cup)
        de = float(delta_e_2000(lab, target_lab))
        its.append(LoopIteration(it, c.tolist(), cup.tolist(), lab.tolist(), de))
        if de <= tolerance_de:
            return LoopResult(True, its, de, f"converged after {it} correction(s)")
        if it == max_iter:
            break
        actual = cup / cup.sum()
        step = correction_step(model, idx, actual, target_lab, lab, damping=damping)
        c = step.fractions
        if mode == "additions":
            adds, _ = additions_for(cup, c)
            its[-1].additions_ml = adds.tolist()
            cup = cup + dispense(adds)
        else:
            cup = dispense(c * batch_ml)
    return LoopResult(
        False, its, its[-1].de, f"not converged after {max_iter} corrections (dE {its[-1].de:.2f})"
    )
