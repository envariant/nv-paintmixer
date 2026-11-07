"""Spectral grid, resampling and tristimulus weighting.

Convention: reflectance in 0-1 on 31 bands, 400-700 nm at 10 nm (:data:`WAVELENGTHS`).
Spectra measured on other grids (the ColorMunki reports 380-730 nm) are resampled by linear
interpolation. Tristimulus weights follow ASTM E2022 at 10 nm intervals; the weight of bands
outside 400-700 nm is folded into the end bands (the ASTM E308 convention for truncated data,
i.e. reflectance is assumed constant beyond the measured range).
"""

from __future__ import annotations

import warnings
from enum import StrEnum
from functools import cache

import numpy as np

from paintmixer.colorsci.types import ArrayLike, FloatArray

WAVELENGTHS: FloatArray = np.arange(400.0, 701.0, 10.0)
N_BANDS = WAVELENGTHS.size  # 31

OBSERVER = "CIE 1931 2 Degree Standard Observer"


class Illuminant(StrEnum):
    D65 = "D65"
    D50 = "D50"
    A = "A"
    F11 = "F11"


_COLOUR_ILLUMINANT_NAMES = {
    Illuminant.D65: "D65",
    Illuminant.D50: "D50",
    Illuminant.A: "A",
    Illuminant.F11: "FL11",
}


def resample(
    wavelengths: ArrayLike, values: ArrayLike, *, max_extrapolation_nm: float = 10.0
) -> FloatArray:
    """Linearly resample spectra ``values[..., len(wavelengths)]`` onto :data:`WAVELENGTHS`.

    Values beyond the input range are held at the edge value, but only up to
    ``max_extrapolation_nm``; larger gaps raise ``ValueError``.
    """
    wl = np.asarray(wavelengths, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)
    if wl.ndim != 1 or v.shape[-1] != wl.size:
        raise ValueError(f"values last axis ({v.shape[-1]}) must match wavelengths ({wl.size})")
    order = np.argsort(wl)
    wl, v = wl[order], v[..., order]
    if wl[0] - WAVELENGTHS[0] > max_extrapolation_nm or (
        WAVELENGTHS[-1] - wl[-1] > max_extrapolation_nm
    ):
        raise ValueError(
            f"input covers {wl[0]:.0f}-{wl[-1]:.0f} nm; need 400-700 nm "
            f"(within {max_extrapolation_nm:.0f} nm)"
        )
    if np.array_equal(wl, WAVELENGTHS):
        return v.copy()
    flat = v.reshape(-1, wl.size)
    out = np.stack([np.interp(WAVELENGTHS, wl, row) for row in flat])
    return out.reshape(*v.shape[:-1], N_BANDS)


@cache
def _weights(illuminant: Illuminant) -> FloatArray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import colour

        full = colour.SpectralShape(360, 830, 1)
        cmfs = colour.MSDS_CMFS[OBSERVER].copy().align(full)
        sd = colour.SDS_ILLUMINANTS[_COLOUR_ILLUMINANT_NAMES[illuminant]].copy().align(full)
        w = colour.colorimetry.tristimulus_weighting_factors_ASTME2022(
            cmfs, sd, colour.SpectralShape(400, 700, 10)
        )
    w = np.asarray(w, dtype=np.float64)  # (48, 3) on 360..830 / 10 nm
    wl_full = np.arange(360.0, 831.0, 10.0)
    inside = (wl_full >= 400) & (wl_full <= 700)
    out = w[inside].copy()
    out[0] += w[wl_full < 400].sum(axis=0)
    out[-1] += w[wl_full > 700].sum(axis=0)
    out *= 100.0 / out[:, 1].sum()
    result: FloatArray = np.ascontiguousarray(out.T, dtype=np.float64)  # (3, 31)
    result.flags.writeable = False  # cached: shared between callers
    return result


def weighting_matrix(illuminant: Illuminant | str = Illuminant.D65) -> FloatArray:
    """Return ``W`` (3, 31) such that ``XYZ = R @ W.T``, with Y(perfect white) = 100."""
    return _weights(Illuminant(illuminant))


def white_point(illuminant: Illuminant | str = Illuminant.D65) -> FloatArray:
    """XYZ of the perfect reflector under ``illuminant`` (Y = 100)."""
    return weighting_matrix(illuminant).sum(axis=1)


def reflectance_to_xyz(
    reflectance: ArrayLike, illuminant: Illuminant | str = Illuminant.D65
) -> FloatArray:
    """Integrate reflectance ``(..., 31)`` to XYZ ``(..., 3)`` on the 0-100 scale."""
    r = np.asarray(reflectance, dtype=np.float64)
    if r.shape[-1] != N_BANDS:
        raise ValueError(f"reflectance must have {N_BANDS} bands, got {r.shape[-1]}")
    xyz: FloatArray = r @ weighting_matrix(illuminant).T
    return xyz
