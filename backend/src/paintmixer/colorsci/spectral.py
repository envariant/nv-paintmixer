"""Spectral grid, resampling and tristimulus weighting.

Convention: reflectance in 0-1 on 36 bands, 380-730 nm at 10 nm (:data:`WAVELENGTHS`) -- the
full range the ColorMunki / i1Studio report. Inputs must cover at least 400-700 nm
(:data:`REQUIRED_RANGE`); other grids are resampled by linear interpolation and bands outside the
input's range are held at its edge value. Tristimulus weights follow ASTM E2022 at 10 nm; the
weight of wavelengths outside 380-730 nm is folded into the end bands (the ASTM E308 convention
for truncated data). Holding a 400-700 nm spectrum flat to 380-730 nm therefore gives the same
colorimetry as folding at 400/700 nm.
"""

from __future__ import annotations

import warnings
from enum import StrEnum
from functools import cache

import numpy as np

from paintmixer.colorsci.types import ArrayLike, FloatArray

WAVELENGTHS: FloatArray = np.arange(380.0, 731.0, 10.0)
N_BANDS = WAVELENGTHS.size  # 36
REQUIRED_RANGE = (400.0, 700.0)  # minimum coverage of an input spectrum
# bands inside 400-700 nm, e.g. for checks that only make sense in the visible core
CORE = (REQUIRED_RANGE[0] <= WAVELENGTHS) & (REQUIRED_RANGE[1] >= WAVELENGTHS)

OBSERVER = "CIE 1931 2 Degree Standard Observer"


class Illuminant(StrEnum):
    """CIE illuminants the backend can integrate under. The UI groups them into series
    (:mod:`paintmixer.colorsci.illuminants`)."""

    D50 = "D50"
    D55 = "D55"
    D65 = "D65"
    D75 = "D75"
    D93 = "D93"
    A = "A"
    F2 = "F2"
    F7 = "F7"
    F11 = "F11"
    F12 = "F12"
    LED_B1 = "LED-B1"
    LED_B2 = "LED-B2"
    LED_B3 = "LED-B3"
    LED_B4 = "LED-B4"
    LED_B5 = "LED-B5"
    ID50 = "ID50"
    ID65 = "ID65"


# names in ``colour.SDS_ILLUMINANTS``; D93 is synthesised from the CIE daylight model
_COLOUR_ILLUMINANT_NAMES = {
    Illuminant.D50: "D50",
    Illuminant.D55: "D55",
    Illuminant.D65: "D65",
    Illuminant.D75: "D75",
    Illuminant.A: "A",
    Illuminant.F2: "FL2",
    Illuminant.F7: "FL7",
    Illuminant.F11: "FL11",
    Illuminant.F12: "FL12",
    Illuminant.LED_B1: "LED-B1",
    Illuminant.LED_B2: "LED-B2",
    Illuminant.LED_B3: "LED-B3",
    Illuminant.LED_B4: "LED-B4",
    Illuminant.LED_B5: "LED-B5",
    Illuminant.ID50: "ID50",
    Illuminant.ID65: "ID65",
}
# nominal CCT (K) of the synthesised daylight illuminants; 1.4388/1.4380 rescales to the
# modern c2, as for D50/D55/D65/D75 in the CIE tables
_SYNTH_DAYLIGHT_K = {Illuminant.D93: 9300.0}


def _illuminant_sd(illuminant: Illuminant) -> object:
    import colour

    if illuminant in _SYNTH_DAYLIGHT_K:
        from colour.temperature import CCT_to_xy_CIE_D

        xy = CCT_to_xy_CIE_D(_SYNTH_DAYLIGHT_K[illuminant] * 1.4388 / 1.4380)
        return colour.sd_CIE_illuminant_D_series(xy)
    return colour.SDS_ILLUMINANTS[_COLOUR_ILLUMINANT_NAMES[illuminant]].copy()


def resample(
    wavelengths: ArrayLike, values: ArrayLike, *, max_extrapolation_nm: float = 10.0
) -> FloatArray:
    """Linearly resample spectra ``values[..., len(wavelengths)]`` onto :data:`WAVELENGTHS`.

    The input must cover :data:`REQUIRED_RANGE` (400-700 nm) to within
    ``max_extrapolation_nm``; otherwise ``ValueError``. Bands beyond the input range (e.g.
    380-390 and 710-730 nm for a 400-700 nm file) are held at the edge value.
    """
    wl = np.asarray(wavelengths, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)
    if wl.ndim != 1 or v.shape[-1] != wl.size:
        raise ValueError(f"values last axis ({v.shape[-1]}) must match wavelengths ({wl.size})")
    order = np.argsort(wl)
    wl, v = wl[order], v[..., order]
    if wl[0] - REQUIRED_RANGE[0] > max_extrapolation_nm or (
        REQUIRED_RANGE[1] - wl[-1] > max_extrapolation_nm
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
        sd = _illuminant_sd(illuminant).align(full)  # type: ignore[attr-defined]
        w = colour.colorimetry.tristimulus_weighting_factors_ASTME2022(
            cmfs, sd, colour.SpectralShape(380, 730, 10)
        )
    w = np.asarray(w, dtype=np.float64)  # (48, 3) on 360..830 / 10 nm
    wl_full = np.arange(360.0, 831.0, 10.0)
    lo, hi = WAVELENGTHS[0], WAVELENGTHS[-1]
    inside = (wl_full >= lo) & (wl_full <= hi)
    out = w[inside].copy()
    out[0] += w[wl_full < lo].sum(axis=0)
    out[-1] += w[wl_full > hi].sum(axis=0)
    out *= 100.0 / out[:, 1].sum()
    result: FloatArray = np.ascontiguousarray(out.T, dtype=np.float64)  # (3, N_BANDS)
    result.flags.writeable = False  # cached: shared between callers
    return result


def weighting_matrix(illuminant: Illuminant | str = Illuminant.D65) -> FloatArray:
    """Return ``W`` (3, N_BANDS) such that ``XYZ = R @ W.T``, with Y(perfect white) = 100."""
    return _weights(Illuminant(illuminant))


def white_point(illuminant: Illuminant | str = Illuminant.D65) -> FloatArray:
    """XYZ of the perfect reflector under ``illuminant`` (Y = 100)."""
    return weighting_matrix(illuminant).sum(axis=1)


def reflectance_to_xyz(
    reflectance: ArrayLike, illuminant: Illuminant | str = Illuminant.D65
) -> FloatArray:
    """Integrate reflectance ``(..., N_BANDS)`` to XYZ ``(..., 3)`` on the 0-100 scale."""
    r = np.asarray(reflectance, dtype=np.float64)
    if r.shape[-1] != N_BANDS:
        raise ValueError(f"reflectance must have {N_BANDS} bands, got {r.shape[-1]}")
    xyz: FloatArray = r @ weighting_matrix(illuminant).T
    return xyz
