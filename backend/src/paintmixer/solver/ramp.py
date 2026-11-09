"""Palette ramps between two paints (tint ladders when one of them is white).

Predictions are opaque films (R∞ with Saunderson), the same as the solver uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.types import FloatArray

RampScale = Literal["linear", "log"]


@dataclass(frozen=True)
class RampStep:
    fraction_a: float  # volume fraction of paint A (the rest is paint B)
    reflectance: FloatArray
    lab: tuple[float, float, float]
    hex: str
    out_of_srgb_gamut: bool


def ramp_fractions(
    steps: int, scale: RampScale = "linear", min_fraction: float = 0.01
) -> FloatArray:
    """Fractions of paint A from 1 down to 0 (linear) or to ``min_fraction`` (log, for tint
    ladders: each step dilutes A by the same factor)."""
    if steps < 2:
        raise ValueError("a ramp needs at least 2 steps")
    if scale == "linear":
        return np.linspace(1.0, 0.0, steps)
    if not 0 < min_fraction < 1:
        raise ValueError("min_fraction must be in (0, 1) for a log ramp")
    return np.geomspace(1.0, min_fraction, steps)


def ramp(
    model: KMModel, index_a: int, index_b: int, fractions: Sequence[float] | FloatArray
) -> list[RampStep]:
    f = np.asarray(fractions, dtype=np.float64)
    c = np.zeros((f.size, model.n_paints))
    c[:, index_a] = f
    c[:, index_b] += 1.0 - f
    R = model.reflectance(c)
    lab = reflectance_to_lab(R)
    rgb = reflectance_to_srgb(R)
    return [
        RampStep(
            float(f[i]),
            R[i],
            (float(lab[i, 0]), float(lab[i, 1]), float(lab[i, 2])),
            srgb_to_hex(rgb.rgb[i]),
            bool(rgb.out_of_gamut[i]),
        )
        for i in range(f.size)
    ]
