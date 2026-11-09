"""Multi-paint mixture arrays: preview every mix of up to six paints at once.

Two generators, both returning integer *parts* per paint (fractions = parts / sum):

* :func:`simplex_lattice` -- all mixtures of ``k`` paints in steps of ``1/divisions``
  (``C(divisions + k - 1, k - 1)`` cells; e.g. a triangle of mixes for three paints). Order:
  lexicographic with the first paint's parts descending, so the first cell is pure paint 1.
* :func:`grid_parts` -- an N-dimensional array: each paint is an axis with its own levels (in
  parts), so the result keeps its shape, e.g. ``white [0, 2, 4, 8] x blue [0, 1] x yellow
  [0, 1, 2]``. C order (the last paint varies fastest). The all-zero cell is kept, as an empty
  cell, so the array shape stays intact; proportional cells (1:1 and 2:2) are the same mixture.

:func:`polygon_layout` places any mixture in 2-D (paints on the vertices of a regular polygon,
first paint at the top), so arrays of more than three paints can still be drawn. Predictions are
opaque films, like the solver's and the ramps'.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from math import comb

import numpy as np

from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.types import FloatArray

MAX_PAINTS = 6
MAX_CELLS = 10_000


class MultimixError(ValueError):
    pass


def lattice_size(k: int, divisions: int, interior: bool = False) -> int:
    if interior:
        return comb(divisions - 1, k - 1) if divisions >= k else 0
    return comb(divisions + k - 1, k - 1)


def _compositions(total: int, k: int, low: int) -> Iterator[tuple[int, ...]]:
    if k == 1:
        if total >= low:
            yield (total,)
        return
    for first in range(total - low * (k - 1), low - 1, -1):
        for rest in _compositions(total - first, k - 1, low):
            yield (first, *rest)


def simplex_lattice(k: int, divisions: int, interior: bool = False) -> np.ndarray:
    """Integer parts ``(n, k)`` summing to ``divisions``; ``interior`` keeps every paint >= 1."""
    if not 1 <= k <= MAX_PAINTS:
        raise MultimixError(f"1 to {MAX_PAINTS} paints, got {k}")
    if divisions < 1:
        raise MultimixError("divisions must be >= 1")
    n = lattice_size(k, divisions, interior)
    if n > MAX_CELLS:
        raise MultimixError(f"{n} cells exceed the limit of {MAX_CELLS}; use fewer divisions")
    if n == 0:
        raise MultimixError(f"interior lattices need divisions >= {k}")
    return np.array(list(_compositions(divisions, k, 1 if interior else 0)), dtype=np.int64)


def grid_parts(levels: Sequence[Sequence[float]]) -> tuple[tuple[int, ...], FloatArray]:
    """``(shape, parts)`` for the N-D product of per-paint levels, in C order."""
    k = len(levels)
    if not 1 <= k <= MAX_PAINTS:
        raise MultimixError(f"1 to {MAX_PAINTS} paints, got {k}")
    if any(len(lv) == 0 for lv in levels):
        raise MultimixError("every paint needs at least one level")
    if any(v < 0 for lv in levels for v in lv):
        raise MultimixError("levels must be >= 0 (parts of each paint)")
    shape = tuple(len(lv) for lv in levels)
    n = int(np.prod(shape))
    if n > MAX_CELLS:
        raise MultimixError(f"{n} cells exceed the limit of {MAX_CELLS}; use fewer levels")
    idx = np.array(list(np.ndindex(*shape)), dtype=np.int64).reshape(n, k)
    parts = np.stack([np.asarray(levels[j], dtype=np.float64)[idx[:, j]] for j in range(k)], axis=1)
    return shape, parts


def polygon_layout(fractions: FloatArray) -> FloatArray:
    """2-D position of each mixture: paints on a regular polygon's vertices, first at the top."""
    f = np.asarray(fractions, dtype=np.float64)
    k = f.shape[1]
    if k == 1:
        return np.zeros((f.shape[0], 2))
    ang = np.pi / 2 + 2 * np.pi * np.arange(k) / k
    if k == 2:
        ang = np.array([np.pi, 0.0])
    vertices = np.stack([np.cos(ang), np.sin(ang)], axis=1)
    out: FloatArray = f @ vertices
    return out


@dataclass(frozen=True)
class MixCell:
    parts: tuple[float, ...]
    fractions: tuple[float, ...] | None  # None for the empty (all-zero) cell
    reflectance: FloatArray | None
    lab: tuple[float, float, float] | None
    hex: str | None
    out_of_srgb_gamut: bool | None
    xy: tuple[float, float] | None


def multimix(model: KMModel, indices: Sequence[int], parts: FloatArray) -> list[MixCell]:
    """Predict every row of ``parts`` (paints = ``indices`` into ``model``) in one batch."""
    p = np.asarray(parts, dtype=np.float64)
    tot = p.sum(axis=1)
    ok = tot > 0
    frac = np.zeros_like(p)
    frac[ok] = p[ok] / tot[ok, None]
    cells: list[MixCell] = []
    R = lab = rgb = oog = xy = None
    if ok.any():
        c = np.zeros((int(ok.sum()), model.n_paints))
        c[:, list(indices)] = frac[ok]
        R = model.reflectance(c)
        lab = reflectance_to_lab(R)
        s = reflectance_to_srgb(R)
        rgb, oog = s.rgb, s.out_of_gamut
        xy = polygon_layout(frac[ok])
    j = 0
    for i in range(p.shape[0]):
        if not ok[i]:
            cells.append(MixCell(tuple(float(x) for x in p[i]), None, None, None, None, None, None))
            continue
        assert R is not None and lab is not None and rgb is not None and oog is not None
        assert xy is not None
        cells.append(
            MixCell(
                tuple(float(x) for x in p[i]),
                tuple(float(x) for x in frac[i]),
                R[j],
                (float(lab[j, 0]), float(lab[j, 1]), float(lab[j, 2])),
                srgb_to_hex(rgb[j]),
                bool(oog[j]),
                (float(xy[j, 0]), float(xy[j, 1])),
            )
        )
        j += 1
    return cells
