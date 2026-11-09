"""Two-constant Kubelka-Munk mixing model with Saunderson surface correction.

All functions are vectorised: concentrations ``c`` have shape ``(..., n_paints)`` and the
per-paint coefficients ``K``, ``S`` have shape ``(n_paints, N_BANDS)``. Results have shape
``(..., N_BANDS)``.

* Mixing:            ``K_mix = c @ K``, ``S_mix = c @ S``, ``k = K_mix / S_mix``
* Opaque layer:      ``R_inf = 1 + k - sqrt(k^2 + 2k)``
* Finite layer of optical thickness ``SX`` over a substrate of internal reflectance ``R_g``
  (Kubelka 1948 hyperbolic solution)::

      a = 1 + k,  b = sqrt(a^2 - 1)
      R = (1 - R_g (a - b coth(b SX))) / (a - R_g + b coth(b SX))

* Saunderson: ``R_meas = k1 + (1 - k1)(1 - k2) R / (1 - k2 R)``. ``k1`` is the external
  (specular) surface reflection, 0 when the instrument excludes specular (45/0 geometry);
  ``k2`` the internal reflection, typically 0.4-0.6.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from paintmixer.colorsci.types import ArrayLike, FloatArray

DEFAULT_K1 = 0.0
DEFAULT_K2 = 0.5
_TINY = 1e-12


def mix_ks(c: ArrayLike, k_coef: ArrayLike, s_coef: ArrayLike) -> FloatArray:
    """Mixture K/S ratio ``(c @ K) / (c @ S)``."""
    c_a = np.asarray(c, dtype=np.float64)
    k_mix = c_a @ np.asarray(k_coef, dtype=np.float64)
    s_mix = c_a @ np.asarray(s_coef, dtype=np.float64)
    result: FloatArray = k_mix / np.maximum(s_mix, _TINY)
    return result


def r_inf(ks: ArrayLike) -> FloatArray:
    """Reflectance of an opaque layer from K/S (internal, before Saunderson)."""
    k = np.maximum(np.asarray(ks, dtype=np.float64), 0.0)
    result: FloatArray = 1.0 + k - np.sqrt(k * k + 2.0 * k)
    return result


def dr_inf_dks(ks: ArrayLike) -> FloatArray:
    k = np.maximum(np.asarray(ks, dtype=np.float64), _TINY)
    result: FloatArray = 1.0 - (k + 1.0) / np.sqrt(k * k + 2.0 * k)
    return result


def ks_from_r(r: ArrayLike) -> FloatArray:
    """Inverse of :func:`r_inf`: ``K/S = (1 - R)^2 / (2R)``."""
    r_a = np.clip(np.asarray(r, dtype=np.float64), 1e-6, 1.0)
    result: FloatArray = (1.0 - r_a) ** 2 / (2.0 * r_a)
    return result


def saunderson(r: ArrayLike, k1: float = DEFAULT_K1, k2: float = DEFAULT_K2) -> FloatArray:
    """Internal reflectance -> measured reflectance."""
    r_a = np.asarray(r, dtype=np.float64)
    result: FloatArray = k1 + (1.0 - k1) * (1.0 - k2) * r_a / (1.0 - k2 * r_a)
    return result


def dsaunderson_dr(r: ArrayLike, k1: float = DEFAULT_K1, k2: float = DEFAULT_K2) -> FloatArray:
    r_a = np.asarray(r, dtype=np.float64)
    result: FloatArray = (1.0 - k1) * (1.0 - k2) / (1.0 - k2 * r_a) ** 2
    return result


def inverse_saunderson(
    r_meas: ArrayLike, k1: float = DEFAULT_K1, k2: float = DEFAULT_K2
) -> FloatArray:
    """Measured reflectance -> internal reflectance."""
    x = np.asarray(r_meas, dtype=np.float64) - k1
    result: FloatArray = x / ((1.0 - k1) * (1.0 - k2) + k2 * x)
    return result


def _b_coth(b: FloatArray, sx: FloatArray) -> FloatArray:
    """``b * coth(b * SX)`` with the ``b -> 0`` limit ``1/SX`` handled."""
    z = b * sx
    small = z < 1e-6
    z_safe = np.where(small, 1.0, z)
    big = b / np.tanh(z_safe)
    sx_safe = np.maximum(sx, _TINY)
    lim = 1.0 / sx_safe + b * b * sx_safe / 3.0
    result: FloatArray = np.where(small, lim, big)
    return result


def r_layer(ks: ArrayLike, sx: ArrayLike, r_g: ArrayLike) -> FloatArray:
    """Internal reflectance of a layer with K/S ``ks`` and scattering power ``SX`` over ``r_g``."""
    k = np.maximum(np.asarray(ks, dtype=np.float64), 0.0)
    sx_a = np.maximum(np.asarray(sx, dtype=np.float64), 0.0)
    rg = np.asarray(r_g, dtype=np.float64)
    a = 1.0 + k
    b = np.sqrt(np.maximum(a * a - 1.0, 0.0))
    bc = _b_coth(b, sx_a)
    result: FloatArray = (1.0 - rg * (a - bc)) / (a - rg + bc)
    return result


@dataclass(frozen=True)
class KMModel:
    """K/S coefficients for a set of paints plus Saunderson constants."""

    K: FloatArray  # (n_paints, N_BANDS)
    S: FloatArray  # (n_paints, N_BANDS)
    k1: float = DEFAULT_K1
    k2: float = DEFAULT_K2

    def __post_init__(self) -> None:
        if self.K.shape != self.S.shape or self.K.ndim != 2:
            raise ValueError("K and S must both have shape (n_paints, n_bands)")

    @property
    def n_paints(self) -> int:
        return int(self.K.shape[0])

    def subset(self, idx: ArrayLike) -> KMModel:
        i = np.asarray(idx, dtype=np.int64)
        return KMModel(K=self.K[i], S=self.S[i], k1=self.k1, k2=self.k2)

    def ks(self, c: ArrayLike) -> FloatArray:
        return mix_ks(c, self.K, self.S)

    def reflectance(self, c: ArrayLike) -> FloatArray:
        """Measured reflectance of an opaque (hiding) layer of mixture ``c``."""
        return saunderson(r_inf(self.ks(c)), self.k1, self.k2)

    def reflectance_layer(
        self, c: ArrayLike, thickness: ArrayLike, substrate_meas: ArrayLike
    ) -> FloatArray:
        """Measured reflectance of a finite layer over a substrate.

        ``thickness`` is optical thickness per unit S, broadcastable to ``(..., N_BANDS)`` (in the
        fit this is ``tau(lambda) * gap_um``). ``substrate_meas`` is the *measured* substrate
        reflectance; it is converted to internal reflectance with the same Saunderson constants.
        """
        c_a = np.asarray(c, dtype=np.float64)
        s_mix = c_a @ self.S
        k_mix = c_a @ self.K
        ks = k_mix / np.maximum(s_mix, _TINY)
        sx = s_mix * np.asarray(thickness, dtype=np.float64)
        rg = inverse_saunderson(substrate_meas, self.k1, self.k2)
        return saunderson(r_layer(ks, sx, rg), self.k1, self.k2)


def contrast_ratio(r_over_black: ArrayLike, r_over_white: ArrayLike) -> FloatArray:
    """Opacity indicator: ratio of luminous reflectance over black to over white (1 = opaque).

    Inputs are Y values (or any luminance-like scalar per sample).
    """
    rb = np.asarray(r_over_black, dtype=np.float64)
    rw = np.maximum(np.asarray(r_over_white, dtype=np.float64), _TINY)
    result: FloatArray = rb / rw
    return result
