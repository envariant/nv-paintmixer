"""Tinting strength of each paint, derived from fitted K/S.

Following the reduction method of ISO 787-24, a paint's colour strength is the Kubelka-Munk K/S
of a standard reduction with white -- here 10 % paint / 90 % white by volume -- at its wavelength
of maximum absorption (searched in 400-700 nm). Relative tinting strength compares two models of
the same paint (e.g. a new batch against the previous calibration) at the reference's peak
wavelength: 100 % = equally strong, 120 % = 20 % less paint needed for the same depth.

The absolute number depends on the white it is reduced with, so it is only comparable between
paints reduced with the same white.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.spectral import CORE, WAVELENGTHS
from paintmixer.colorsci.types import FloatArray

REDUCTION = 0.10  # paint volume fraction in the white reduction (1:9)


@dataclass(frozen=True)
class PaintStrength:
    paint_id: str
    reduction_fraction: float
    reduction_ks: float  # K/S of the reduction at its absorption peak
    peak_nm: float
    reduction_lab: tuple[float, float, float]
    reduction_hex: str
    ks_spectrum: FloatArray  # K/S of the reduction per band (for comparisons)
    relative_pct: float | None = None


def tinting_strengths(
    model: KMModel, paint_ids: Sequence[str], white_id: str, reduction: float = REDUCTION
) -> dict[str, PaintStrength]:
    """Strength of every non-white paint in ``model`` reduced with ``white_id``."""
    if white_id not in paint_ids:
        raise ValueError(f"white {white_id!r} is not in the model")
    w = list(paint_ids).index(white_id)
    out: dict[str, PaintStrength] = {}
    for i, pid in enumerate(paint_ids):
        if i == w:
            continue
        c = np.zeros(model.n_paints)
        c[i], c[w] = reduction, 1.0 - reduction
        ks = model.ks(c)
        core = np.where(CORE, ks, -np.inf)
        j = int(np.argmax(core))
        r = model.reflectance(c)
        lab = reflectance_to_lab(r)
        out[pid] = PaintStrength(
            pid,
            reduction,
            float(ks[j]),
            float(WAVELENGTHS[j]),
            (float(lab[0]), float(lab[1]), float(lab[2])),
            srgb_to_hex(reflectance_to_srgb(r).rgb),
            ks,
        )
    return out


def relative_strength(test: PaintStrength, reference: PaintStrength) -> float:
    """Relative tinting strength (%) of ``test`` vs ``reference`` at the reference's peak."""
    j = int(np.flatnonzero(reference.peak_nm == WAVELENGTHS)[0])
    return float(100.0 * test.ks_spectrum[j] / reference.ks_spectrum[j])


def with_relative(
    strengths: dict[str, PaintStrength], reference: dict[str, PaintStrength]
) -> dict[str, PaintStrength]:
    """Copy of ``strengths`` with ``relative_pct`` filled for paints present in ``reference``."""
    from dataclasses import replace

    return {
        pid: replace(s, relative_pct=relative_strength(s, reference[pid]))
        if pid in reference
        else s
        for pid, s in strengths.items()
    }
