"""Palette ramps between two paints (tint ladders when one of them is white).

A convenience layer over :mod:`paintmixer.solver.multimix`: a ramp is a two-paint mixture array,
predicted by :func:`~paintmixer.solver.multimix.multimix`. A *linear* ramp with ``n`` steps is
exactly a two-paint simplex lattice with ``n - 1`` divisions (same fractions, same order); what
ramps add is the *log* scale (each step dilutes paint A by the same factor, the usual tint
ladder), which a simplex lattice cannot express. Predictions are opaque films, like the solver's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.types import FloatArray
from paintmixer.solver.multimix import multimix

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
    """Predicted swatches for paint A (``index_a``) mixed into paint B at ``fractions`` of A."""
    if index_a == index_b:
        raise ValueError("a ramp needs two different paints")
    f = np.asarray(fractions, dtype=np.float64)
    if f.ndim != 1 or np.any((f < 0) | (f > 1)):
        raise ValueError("fractions of paint A must be in [0, 1]")
    cells = multimix(model, [index_a, index_b], np.column_stack([f, 1.0 - f]))
    steps = []
    for frac, cell in zip(f, cells, strict=True):
        # parts always sum to 1 here, so every cell has a prediction
        assert cell.reflectance is not None and cell.lab is not None and cell.hex is not None
        steps.append(
            RampStep(
                float(frac), cell.reflectance, cell.lab, cell.hex, bool(cell.out_of_srgb_gamut)
            )
        )
    return steps
