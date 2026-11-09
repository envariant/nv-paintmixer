"""Approximate K/S from swatch colours, for trying PaintMixer before calibrating.

Each paint needs its masstone swatch (an opaque chip, e.g. from the manufacturer's colour card)
and optionally a tint swatch at a known reduction with white (e.g. 1:9). Spectra are
reconstructed from the colours (Jakob & Hanika 2019), so this model is a *metameric guess*:

* the masstone gives each paint's K/S ratio per band (assuming the chip is opaque);
* scattering S is not visible in a masstone. With a tint swatch, S is the single value that best
  reproduces the tint's colour (dE2000) when the paint is reduced with the white. Without one a
  default S relative to white is assumed and flagged.

Absorption K always comes from the masstone, so each paint reproduces its own chip exactly. Using
the tint for K as well was tried: mixtures improved only slightly (median 3.7 vs 4.3 dE2000 on
the synthetic set) while masstones drifted by up to 10 dE2000.

Expect errors of several dE2000 on mixtures; calibrate for real recipes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize_scalar

from paintmixer.calibration.synthetic import substrate_black, substrate_white, true_tau
from paintmixer.colorsci.convert import reflectance_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.km import (
    DEFAULT_K1,
    DEFAULT_K2,
    inverse_saunderson,
    ks_from_r,
    r_inf,
    saunderson,
)
from paintmixer.colorsci.recovery import lab_to_reflectance
from paintmixer.colorsci.types import FloatArray
from paintmixer.domain import PaintRole

DEFAULT_SCATTERING = 0.3  # S relative to the white, when no tint swatch is given
S_RANGE = (0.01, 5.0)
TINT_MATCH_WARN_DE = 2.0


@dataclass(frozen=True)
class SwatchPaint:
    paint_id: str
    role: PaintRole
    masstone_lab: FloatArray
    tint_lab: FloatArray | None = None
    tint_fraction: float = 0.1  # paint volume fraction in the tint swatch


@dataclass
class SwatchModel:
    paint_ids: list[str]
    K: FloatArray
    S: FloatArray
    tau: FloatArray
    k1: float
    k2: float
    substrate_white: FloatArray
    substrate_black: FloatArray
    scattering_source: dict[str, str]  # "white" | "tint" | "assumed"
    warnings: list[str] = field(default_factory=list)
    tint_match_de: dict[str, float] = field(default_factory=dict)  # dE2000 of the S fit


class SwatchError(ValueError):
    pass


def _internal_ks(lab: FloatArray, k1: float, k2: float) -> FloatArray:
    r = lab_to_reflectance(lab)
    return ks_from_r(inverse_saunderson(r, k1, k2))


def scattering_from_tint(
    ks_mass: FloatArray,
    k_white: FloatArray,
    tint_lab: FloatArray,
    fraction: float,
    k1: float = DEFAULT_K1,
    k2: float = DEFAULT_K2,
) -> tuple[float, float]:
    """Single S (relative to white S = 1) that best reproduces the tint swatch's colour.

    With ``K_p = ks_mass * S`` (the masstone fixes the ratio), the reduction
    ``fraction * paint + (1 - fraction) * white`` is predicted for each S and the dE2000 to the
    tint swatch minimised over log S in :data:`S_RANGE`. Matching the *colour* is deliberate:
    the masstone and tint spectra are reconstructed independently, so a band-by-band solution
    would fit reconstruction artefacts. Returns ``(S, dE2000 of the best match)``.
    """
    c = fraction

    def de(log_s: float) -> float:
        s_p = float(np.exp(log_s))
        ks = (c * ks_mass * s_p + (1 - c) * k_white) / (c * s_p + (1 - c))
        lab = reflectance_to_lab(saunderson(r_inf(ks), k1, k2))
        return float(delta_e_2000(lab, tint_lab))

    lo, hi = np.log(S_RANGE[0]), np.log(S_RANGE[1])
    grid = np.linspace(lo, hi, 41)
    vals = [de(g) for g in grid]
    j = int(np.argmin(vals))
    res = minimize_scalar(
        de, bounds=(grid[max(j - 1, 0)], grid[min(j + 1, len(grid) - 1)]), method="bounded"
    )
    best = float(res.x) if res.fun <= vals[j] else float(grid[j])
    return float(np.exp(best)), min(float(res.fun), vals[j])


def model_from_swatches(
    paints: Sequence[SwatchPaint],
    *,
    k1: float = DEFAULT_K1,
    k2: float = DEFAULT_K2,
    default_scattering: float = DEFAULT_SCATTERING,
) -> SwatchModel:
    whites = [p for p in paints if p.role == PaintRole.WHITE]
    if not whites:
        raise SwatchError("a white paint with a swatch is required (it fixes the scattering scale)")
    white = whites[0]
    order = [white] + [p for p in paints if p is not white]
    k_white = np.maximum(_internal_ks(white.masstone_lab, k1, k2), 1e-5)
    K, S, src, warnings = [k_white], [np.ones_like(k_white)], {white.paint_id: "white"}, []
    tint_de: dict[str, float] = {}
    for p in order[1:]:
        ks_m = np.maximum(_internal_ks(p.masstone_lab, k1, k2), 1e-5)
        s: float | None = None
        if p.tint_lab is not None:
            s, fit_de = scattering_from_tint(ks_m, k_white, p.tint_lab, p.tint_fraction, k1, k2)
            tint_de[p.paint_id] = fit_de
            if fit_de > TINT_MATCH_WARN_DE:
                warnings.append(
                    f"{p.paint_id}: with a spectrum reconstructed from its masstone colour the "
                    f"model reproduces its tint swatch only to {fit_de:.1f} dE2000 (the real "
                    "absorption shape is unknown); mixtures with this paint are less accurate. "
                    "If the error is very large, check the tint fraction."
                )
            src[p.paint_id] = "tint"
        else:
            warnings.append(
                f"{p.paint_id}: no tint swatch, scattering assumed (S = {default_scattering:g} x "
                "white); tints with white will be approximate."
            )
            src[p.paint_id] = "assumed"
        s_val = default_scattering if s is None else s
        S.append(np.full_like(ks_m, s_val))
        K.append(ks_m * s_val)
    warnings.insert(
        0,
        "Model built from swatch colours (reconstructed spectra, not measurements): expect "
        "several dE2000 of error on mixtures. Calibrate for accurate recipes.",
    )
    return SwatchModel(
        [p.paint_id for p in order],
        np.stack(K),
        np.stack(S),
        true_tau(),
        k1,
        k2,
        substrate_white(),
        substrate_black(),
        src,
        warnings,
        tint_de,
    )
