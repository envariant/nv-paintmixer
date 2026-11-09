"""OKLab / OKLCh (Ottosson 2020) and CSS Color 4 gamut mapping into sRGB.

Gamut mapping follows the CSS Color Module Level 4 "binary search gamut mapping with local
MINDE" algorithm: keep OKLab lightness and hue, reduce OKLCh chroma by bisection, and stop as
soon as clipping the candidate to sRGB moves it by less than a just-noticeable difference
(``JND`` = 0.02 in OKLab units). Compared with plain per-channel clipping this keeps hue and
lightness, which matters when swatches are judged by eye. Everything is vectorised over leading
axes.
"""

from __future__ import annotations

import numpy as np

from paintmixer.colorsci.types import ArrayLike, FloatArray

# linear sRGB -> LMS and non-linear LMS -> OKLab (Ottosson 2020)
_M1: FloatArray = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_M2: FloatArray = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_M1_INV: FloatArray = np.linalg.inv(_M1)
_M2_INV: FloatArray = np.linalg.inv(_M2)

JND = 0.02
EPSILON = 1e-4


def lrgb_to_oklab(lrgb: ArrayLike) -> FloatArray:
    lms = np.asarray(lrgb, dtype=np.float64) @ _M1.T
    out: FloatArray = np.cbrt(lms) @ _M2.T
    return out


def oklab_to_lrgb(oklab: ArrayLike) -> FloatArray:
    lms_ = np.asarray(oklab, dtype=np.float64) @ _M2_INV.T
    out: FloatArray = (lms_**3) @ _M1_INV.T
    return out


def oklab_to_oklch(oklab: ArrayLike) -> FloatArray:
    lab = np.asarray(oklab, dtype=np.float64)
    c = np.hypot(lab[..., 1], lab[..., 2])
    h = np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360.0
    return np.stack([lab[..., 0], c, h], axis=-1)


def oklch_to_oklab(oklch: ArrayLike) -> FloatArray:
    lch = np.asarray(oklch, dtype=np.float64)
    h = np.radians(lch[..., 2])
    return np.stack([lch[..., 0], lch[..., 1] * np.cos(h), lch[..., 1] * np.sin(h)], axis=-1)


def delta_e_ok(lab1: ArrayLike, lab2: ArrayLike) -> FloatArray:
    d = np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64)
    out: FloatArray = np.linalg.norm(d, axis=-1)
    return out


def in_gamut(lrgb: ArrayLike, tolerance: float = 1e-6) -> np.ndarray:
    v = np.asarray(lrgb, dtype=np.float64)
    return np.all((v >= -tolerance) & (v <= 1.0 + tolerance), axis=-1)


def gamut_map_lrgb(
    lrgb: ArrayLike, *, jnd: float = JND, epsilon: float = EPSILON, max_iter: int = 40
) -> FloatArray:
    """Map linear sRGB ``(..., 3)`` into the sRGB gamut (CSS Color 4 algorithm)."""
    v = np.asarray(lrgb, dtype=np.float64)
    flat = v.reshape(-1, 3)
    out = np.clip(flat, 0.0, 1.0)
    origin = lrgb_to_oklab(flat)
    L = origin[:, 0]
    need = ~in_gamut(flat) & (L > 0.0) & (L < 1.0)
    out[L >= 1.0] = 1.0
    out[L <= 0.0] = 0.0
    idx = np.flatnonzero(need)
    if idx.size:
        lch = oklab_to_oklch(origin[idx])
        clipped = np.clip(flat[idx], 0.0, 1.0)
        e = delta_e_ok(lrgb_to_oklab(clipped), origin[idx])
        done = e < jnd  # clipping alone is already imperceptible
        lo = np.zeros(idx.size)
        hi = lch[:, 1].copy()
        lo_in = np.ones(idx.size, dtype=bool)
        for _ in range(max_iter):
            active = ~done & (hi - lo > epsilon)
            if not active.any():
                break
            chroma = (lo + hi) / 2.0
            cand_lab = oklch_to_oklab(np.stack([lch[:, 0], chroma, lch[:, 2]], axis=-1))
            cand = oklab_to_lrgb(cand_lab)
            ok = in_gamut(cand)
            case_in = active & lo_in & ok
            lo = np.where(case_in, chroma, lo)
            rest = active & ~case_in
            cl = np.clip(cand, 0.0, 1.0)
            e = delta_e_ok(lrgb_to_oklab(cl), cand_lab)
            clipped = np.where(rest[:, None], cl, clipped)
            close = rest & (e < jnd)
            finish = close & (jnd - e < epsilon)
            done = done | finish
            moving = close & ~finish
            lo_in = np.where(moving, False, lo_in)
            lo = np.where(moving, chroma, lo)
            hi = np.where(rest & ~close, chroma, hi)
        out[idx] = clipped
    result: FloatArray = out.reshape(v.shape)
    return result
