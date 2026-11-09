"""Plausible reflectance reconstruction for targets given only as Lab/sRGB.

Uses Jakob & Hanika (2019) sigmoid-polynomial recovery from colour-science (smooth, bounded
0-1 spectra), falling back to Otsu et al. (2018) if the optimisation fails. The result is only
used to initialise the solver and as a reference for metamerism estimates; it is *not* a
measurement.
"""

from __future__ import annotations

import warnings

import numpy as np

from paintmixer.colorsci.convert import lab_to_xyz
from paintmixer.colorsci.spectral import WAVELENGTHS, Illuminant, white_point
from paintmixer.colorsci.types import ArrayLike, FloatArray


def lab_to_reflectance(lab: ArrayLike) -> FloatArray:
    """Recover a smooth reflectance (N_BANDS bands) whose D65 Lab approximates ``lab``."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import colour

        xyz = lab_to_xyz(np.asarray(lab, dtype=np.float64), white_point(Illuminant.D65)) / 100.0
        try:
            sd = colour.XYZ_to_sd(
                xyz, method="Jakob 2019", illuminant=colour.SDS_ILLUMINANTS["D65"]
            )
        except Exception:  # pragma: no cover - fallback path
            sd = colour.XYZ_to_sd(xyz, method="Otsu 2018")
        r = np.array([sd[float(w)] for w in WAVELENGTHS], dtype=np.float64)
    return np.clip(r, 1e-4, 1.0)
