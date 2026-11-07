"""Opaque-film prediction for mixtures of a paint pool, with analytic Lab Jacobians.

The solver works with *subsets*: ``idx`` is an integer array ``(m, k)`` of paint indices into
the pool and ``c`` the matching fractions ``(m, k)``. Everything is batched over ``m``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from paintmixer.colorsci.convert import xyz_to_lab
from paintmixer.colorsci.km import (
    KMModel,
    dr_inf_dks,
    dsaunderson_dr,
    r_inf,
    saunderson,
)
from paintmixer.colorsci.spectral import Illuminant, weighting_matrix, white_point
from paintmixer.colorsci.types import FloatArray, IntArray
from paintmixer.domain import PaintInfo, PaintRole

_EPS = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0


@dataclass
class PoolModel:
    """A K-M model restricted to a pool of paints, plus their metadata."""

    paints: list[PaintInfo]
    km: KMModel
    _w: dict[Illuminant, FloatArray] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if len(self.paints) != self.km.n_paints:
            raise ValueError("paints and model rows differ")

    @classmethod
    def from_model(
        cls, km: KMModel, model_ids: Sequence[str], paints: Sequence[PaintInfo]
    ) -> PoolModel:
        """Select ``paints`` (in the given order) out of a fitted model with ``model_ids``."""
        pos = {p: i for i, p in enumerate(model_ids)}
        missing = [p.id for p in paints if p.id not in pos]
        if missing:
            raise KeyError(f"paints not in the fitted model: {', '.join(missing)}")
        return cls(list(paints), km.subset([pos[p.id] for p in paints]))

    @property
    def n(self) -> int:
        return len(self.paints)

    @property
    def ids(self) -> list[str]:
        return [p.id for p in self.paints]

    def role_mask(self, role: PaintRole) -> np.ndarray:
        return np.array([p.role == role for p in self.paints])

    @property
    def cost(self) -> FloatArray:
        return np.array([p.cost_per_ml for p in self.paints], dtype=np.float64)

    def W(self, ill: Illuminant) -> FloatArray:
        if ill not in self._w:
            self._w[ill] = weighting_matrix(ill)
        return self._w[ill]

    # -- forward ------------------------------------------------------------------------------

    def reflectance(self, idx: IntArray, c: FloatArray) -> FloatArray:
        K = self.km.K[idx]  # (m, k, 31)
        S = self.km.S[idx]
        num = np.einsum("mk,mkb->mb", c, K)
        den = np.einsum("mk,mkb->mb", c, S)
        return saunderson(r_inf(num / den), self.km.k1, self.km.k2)

    def lab(self, idx: IntArray, c: FloatArray, ill: Illuminant = Illuminant.D65) -> FloatArray:
        return xyz_to_lab(self.reflectance(idx, c) @ self.W(ill).T, white_point(ill))

    def lab_jac(
        self, idx: IntArray, c: FloatArray, ill: Illuminant = Illuminant.D65
    ) -> tuple[FloatArray, FloatArray]:
        """Lab ``(m, 3)`` and ``dLab/dc`` ``(m, 3, k)``."""
        K = self.km.K[idx]
        S = self.km.S[idx]
        num = np.einsum("mk,mkb->mb", c, K)
        den = np.einsum("mk,mkb->mb", c, S)
        ks = num / den
        ri = r_inf(ks)
        dr = dsaunderson_dr(ri, self.km.k1, self.km.k2) * dr_inf_dks(ks)  # (m, 31)
        dks = (K - ks[:, None, :] * S) / den[:, None, :]  # (m, k, 31)
        dR = dks * dr[:, None, :]
        R = saunderson(ri, self.km.k1, self.km.k2)
        W = self.W(ill)
        wp = white_point(ill)
        xyz = R @ W.T
        dxyz = dR @ W.T  # (m, k, 3)
        t = xyz / wp
        f = np.where(t > _EPS, np.cbrt(t), (_KAPPA * t + 16.0) / 116.0)
        df = np.where(t > _EPS, 1.0 / (3.0 * np.cbrt(np.maximum(t, 1e-12)) ** 2), _KAPPA / 116.0)
        dfdc = dxyz * (df / wp)[:, None, :]  # (m, k, 3)
        lab = np.stack(
            [116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2])],
            axis=-1,
        )
        jac = np.stack(
            [
                116.0 * dfdc[:, :, 1],
                500.0 * (dfdc[:, :, 0] - dfdc[:, :, 1]),
                200.0 * (dfdc[:, :, 1] - dfdc[:, :, 2]),
            ],
            axis=1,
        )
        return lab, jac
