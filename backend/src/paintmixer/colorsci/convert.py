"""XYZ, CIELAB and sRGB conversions (vectorised over leading axes).

XYZ is on the 0-100 scale. Lab is relative to a supplied white (defaults to the perfect
reflector under D65 from :func:`paintmixer.colorsci.spectral.white_point`). sRGB uses the
IEC 61966-2-1 primaries and transfer function with its standard D65 white; conversion from
spectra goes through Lab so a perfect reflector maps exactly to sRGB (1, 1, 1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from paintmixer.colorsci.spectral import Illuminant, reflectance_to_xyz, white_point
from paintmixer.colorsci.types import ArrayLike, BoolArray, FloatArray

_EPS = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0

_M_RGB_TO_XYZ: FloatArray = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_M_XYZ_TO_RGB: FloatArray = np.linalg.inv(_M_RGB_TO_XYZ)
# White of the sRGB encoding (row sums of the matrix, ~ [95.047, 100, 108.883]).
SRGB_WHITE: FloatArray = _M_RGB_TO_XYZ.sum(axis=1) * 100.0


def _white(white: ArrayLike | None) -> FloatArray:
    return white_point(Illuminant.D65) if white is None else np.asarray(white, dtype=np.float64)


def xyz_to_lab(xyz: ArrayLike, white: ArrayLike | None = None) -> FloatArray:
    t = np.asarray(xyz, dtype=np.float64) / _white(white)
    f = np.where(t > _EPS, np.cbrt(t), (_KAPPA * t + 16.0) / 116.0)
    lab = np.empty_like(f)
    lab[..., 0] = 116.0 * f[..., 1] - 16.0
    lab[..., 1] = 500.0 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200.0 * (f[..., 1] - f[..., 2])
    return lab


def lab_to_xyz(lab: ArrayLike, white: ArrayLike | None = None) -> FloatArray:
    lab_a = np.asarray(lab, dtype=np.float64)
    fy = (lab_a[..., 0] + 16.0) / 116.0
    fx = fy + lab_a[..., 1] / 500.0
    fz = fy - lab_a[..., 2] / 200.0
    f = np.stack([fx, fy, fz], axis=-1)
    t = np.where(f**3 > _EPS, f**3, (116.0 * f - 16.0) / _KAPPA)
    # L* branch for Y uses L directly (exact inverse of the forward definition)
    ty = np.where(lab_a[..., 0] > _KAPPA * _EPS, fy**3, lab_a[..., 0] / _KAPPA)
    t[..., 1] = ty
    return t * _white(white)


def lab_to_lch(lab: ArrayLike) -> FloatArray:
    lab_a = np.asarray(lab, dtype=np.float64)
    c = np.hypot(lab_a[..., 1], lab_a[..., 2])
    h = np.degrees(np.arctan2(lab_a[..., 2], lab_a[..., 1])) % 360.0
    return np.stack([lab_a[..., 0], c, h], axis=-1)


def _srgb_encode(lin: FloatArray) -> FloatArray:
    a = np.abs(lin)
    enc = np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055)
    return np.sign(lin) * enc


def _srgb_decode(rgb: FloatArray) -> FloatArray:
    a = np.abs(rgb)
    dec = np.where(a <= 0.04045, a / 12.92, np.power((a + 0.055) / 1.055, 2.4))
    return np.sign(rgb) * dec


def srgb_to_lab(rgb: ArrayLike) -> FloatArray:
    """sRGB in 0-1 -> Lab (D65 perfect-reflector white)."""
    lin = _srgb_decode(np.asarray(rgb, dtype=np.float64))
    xyz_srgb = lin @ _M_RGB_TO_XYZ.T * 100.0
    return xyz_to_lab(xyz_srgb, SRGB_WHITE)


@dataclass(frozen=True)
class SrgbResult:
    rgb: FloatArray  # clipped, encoded 0-1
    out_of_gamut: BoolArray


def lab_to_srgb(lab: ArrayLike, *, tolerance: float = 1e-4) -> SrgbResult:
    """Lab (D65) -> encoded sRGB 0-1, clipped, with an out-of-gamut flag per colour."""
    xyz = lab_to_xyz(lab, SRGB_WHITE) / 100.0
    lin = xyz @ _M_XYZ_TO_RGB.T
    oog = np.any((lin < -tolerance) | (lin > 1.0 + tolerance), axis=-1)
    rgb = _srgb_encode(np.clip(lin, 0.0, 1.0))
    return SrgbResult(rgb=np.clip(rgb, 0.0, 1.0), out_of_gamut=np.asarray(oog))


def reflectance_to_lab(
    reflectance: ArrayLike, illuminant: Illuminant | str = Illuminant.D65
) -> FloatArray:
    return xyz_to_lab(reflectance_to_xyz(reflectance, illuminant), white_point(illuminant))


def reflectance_to_srgb(reflectance: ArrayLike) -> SrgbResult:
    """Swatch colour for a reflectance (rendered under D65)."""
    return lab_to_srgb(reflectance_to_lab(reflectance, Illuminant.D65))


def hex_to_srgb(hex_str: str) -> FloatArray:
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        raise ValueError(f"invalid hex colour: {hex_str!r}")
    return np.array([int(s[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255.0


def srgb_to_hex(rgb: ArrayLike) -> str:
    v = np.clip(np.round(np.asarray(rgb, dtype=np.float64) * 255.0), 0, 255).astype(int)
    return "#{:02x}{:02x}{:02x}".format(*v.tolist())
