"""Achievable-colour gamut of a paint pool: a*b* boundaries at L* slices.

The gamut of K-M mixtures is not convex, so we sample mixtures densely (all singles, pairs on a
fine grid, triples on a simplex grid and random 4-5 paint mixtures) and take, for every L* slice
and hue bin, the most chromatic sample. The pre-check interpolates that boundary at the target's
hue; the solver's achieved dE is still the final word.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from paintmixer.colorsci.convert import lab_to_lch
from paintmixer.colorsci.types import FloatArray
from paintmixer.solver.model import PoolModel

L_STEP = 10.0
HUE_BINS = 36


@dataclass
class GamutSlice:
    L: float
    hue_deg: FloatArray  # (HUE_BINS,) bin centres
    chroma: FloatArray  # (HUE_BINS,) max chroma, 0 where no samples
    a: FloatArray
    b: FloatArray


@dataclass
class Gamut:
    slices: list[GamutSlice]
    L_min: float
    L_max: float
    n_samples: int

    def max_chroma(self, L: float, hue: float) -> float:
        """Boundary chroma at (L, hue), linear in L between slices and in hue between bins."""
        if self.L_min - 2.0 > L or self.L_max + 2.0 < L or not self.slices:
            return 0.0
        Ls = np.array([s.L for s in self.slices])
        width = 360.0 / HUE_BINS

        def at(sl: GamutSlice) -> float:
            pos = (hue - width / 2.0) / width
            i0 = int(np.floor(pos)) % HUE_BINS
            i1 = (i0 + 1) % HUE_BINS
            t = pos - np.floor(pos)
            return float((1 - t) * sl.chroma[i0] + t * sl.chroma[i1])

        if Ls[0] >= L:
            return at(self.slices[0])
        if Ls[-1] <= L:
            return at(self.slices[-1])
        j = int(np.searchsorted(Ls, L)) - 1
        t = (L - Ls[j]) / (Ls[j + 1] - Ls[j])
        return float((1 - t) * at(self.slices[j]) + t * at(self.slices[j + 1]))

    def contains(self, lab: FloatArray, margin: float = 2.0) -> bool:
        lch = lab_to_lch(lab)
        if lch[0] < self.L_min - margin or lch[0] > self.L_max + margin:
            return False
        if lch[1] < 3.0:  # near-neutral: inside if L is reachable
            return True
        return bool(lch[1] <= self.max_chroma(float(lch[0]), float(lch[2])) + margin)


def sample_mixtures(model: PoolModel, max_paints: int = 5, seed: int = 0) -> FloatArray:
    """Lab of a dense set of mixtures of the pool.

    Fractions are sampled log-uniformly (``exp(U(-6, 0))`` before normalising) so that very
    pale tints (95-99 % white) and very small additions are covered as well as balanced mixes.
    """
    n = model.n
    rng = np.random.default_rng(seed)
    labs = [model.lab(np.arange(n)[:, None], np.ones((n, 1)))]
    half = np.logspace(-3, np.log10(0.5), 24)
    t = np.concatenate([half, 1.0 - half[::-1]])
    pairs = list(itertools.combinations(range(n), 2))
    if pairs:
        idx = np.repeat(np.array(pairs), t.size, axis=0)
        c = np.stack([np.tile(t, len(pairs)), 1 - np.tile(t, len(pairs))], axis=1)
        labs.append(model.lab(idx, c))
    for k in range(3, min(max_paints, n) + 1):
        combos = list(itertools.combinations(range(n), k))
        per = max(8, 6000 // len(combos))
        if len(combos) * per > 12000:
            pick = rng.choice(len(combos), 12000 // per, replace=False)
            combos = [combos[i] for i in pick]
        idx = np.repeat(np.array(combos), per, axis=0)
        w = np.exp(rng.uniform(-6.0, 0.0, size=idx.shape))
        labs.append(model.lab(idx, w / w.sum(axis=1, keepdims=True)))
    return np.concatenate(labs)


def compute_gamut(model: PoolModel, max_paints: int = 5, seed: int = 0) -> Gamut:
    lab = sample_mixtures(model, max_paints, seed)
    lch = lab_to_lch(lab)
    width = 360.0 / HUE_BINS
    centres: FloatArray = (np.arange(HUE_BINS, dtype=np.float64) + 0.5) * width
    slices = []
    L_min, L_max = float(lch[:, 0].min()), float(lch[:, 0].max())
    for L in np.arange(np.ceil(L_min / L_STEP) * L_STEP, L_max + 1e-9, L_STEP):
        sel = np.abs(lch[:, 0] - L) <= L_STEP / 2.0
        chroma = np.zeros(HUE_BINS)
        if sel.any():
            bins = np.minimum((lch[sel, 2] / width).astype(int), HUE_BINS - 1)
            np.maximum.at(chroma, bins, lch[sel, 1])
        rad = np.radians(centres)
        slices.append(
            GamutSlice(float(L), centres, chroma, chroma * np.cos(rad), chroma * np.sin(rad))
        )
    return Gamut(slices, L_min, L_max, int(lab.shape[0]))
