"""CIEDE2000 colour difference (Sharma, Wu & Dalal 2005), vectorised.

Verified against the Sharma supplementary data set (``tests/data/sharma2005_ciede2000.csv``) and
cross-checked with :func:`colour.delta_E` in the tests. Hue-angle comparisons at exactly
180 degrees use a small tolerance so the result does not depend on platform rounding of
``arctan2`` (Sharma pair 14).
"""

from __future__ import annotations

import numpy as np

from paintmixer.colorsci.types import ArrayLike, FloatArray

_HUE_TOL = 1e-9


def delta_e_2000(
    lab1: ArrayLike, lab2: ArrayLike, k_l: float = 1.0, k_c: float = 1.0, k_h: float = 1.0
) -> FloatArray:
    l1, a1, b1 = np.moveaxis(np.asarray(lab1, dtype=np.float64), -1, 0)
    l2, a2, b2 = np.moveaxis(np.asarray(lab2, dtype=np.float64), -1, 0)

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar7 = ((c1 + c2) / 2.0) ** 7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)
    h1p = np.where((a1p == 0) & (b1 == 0), 0.0, np.degrees(np.arctan2(b1, a1p)) % 360.0)
    h2p = np.where((a2p == 0) & (b2 == 0), 0.0, np.degrees(np.arctan2(b2, a2p)) % 360.0)

    d_l = l2 - l1
    d_c = c2p - c1p
    zero_c = (c1p * c2p) == 0
    dh = h2p - h1p
    dh = np.where(
        dh > 180.0 + _HUE_TOL, dh - 360.0, np.where(dh < -180.0 - _HUE_TOL, dh + 360.0, dh)
    )
    dh = np.where(zero_c, 0.0, dh)
    d_h = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2.0))

    l_bar = (l1 + l2) / 2.0
    c_bar = (c1p + c2p) / 2.0
    h_sum = h1p + h2p
    h_bar = np.where(
        np.abs(h1p - h2p) <= 180.0 + _HUE_TOL,
        h_sum / 2.0,
        np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
    )
    h_bar = np.where(zero_c, h_sum, h_bar)

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar))
        + 0.32 * np.cos(np.radians(3.0 * h_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar - 63.0))
    )
    d_theta = 30.0 * np.exp(-(((h_bar - 275.0) / 25.0) ** 2))
    c_bar7p = c_bar**7
    r_c = 2.0 * np.sqrt(c_bar7p / (c_bar7p + 25.0**7))
    s_l = 1.0 + 0.015 * (l_bar - 50.0) ** 2 / np.sqrt(20.0 + (l_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_bar
    s_h = 1.0 + 0.015 * c_bar * t
    r_t = -np.sin(np.radians(2.0 * d_theta)) * r_c

    tl = d_l / (k_l * s_l)
    tc = d_c / (k_c * s_c)
    th = d_h / (k_h * s_h)
    result: FloatArray = np.sqrt(tl**2 + tc**2 + th**2 + r_t * tc * th)
    return result


def delta_e_76(lab1: ArrayLike, lab2: ArrayLike) -> FloatArray:
    diff = np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64)
    result: FloatArray = np.linalg.norm(diff, axis=-1)
    return result
