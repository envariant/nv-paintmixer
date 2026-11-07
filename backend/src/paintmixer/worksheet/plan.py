"""Calibration worksheet planner: which drawdowns to make, and how much of each paint to weigh.

The rules follow PLAN.md / docs/calibration_format.md:

* substrate references SUB-W and SUB-B;
* masstones of every non-white paint at the standard gap, white as a thickness series;
* tints with white (chromatic 5/15/35/65 %, black 1/3/10/30 % paint by volume);
* every pair of chromatic paints at 25/75, 50/50, 75/25 plus a 50/50 pair with 60 % white;
* near-neutral, dark and random mixtures from a seeded RNG;
* every Nth mixture is flagged ``holdout``.

Each physical drawdown yields two CSV rows (``-W`` and ``-B``) for tints and mixtures; masstones
are drawn over the black-and-white chart, so they also yield one row per background.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from paintmixer.calibration.format import SUFFIX, SampleType, Substrate
from paintmixer.domain import PaintInfo, PaintRole

CHROMATIC_TINTS = (0.05, 0.15, 0.35, 0.65)
BLACK_TINTS = (0.01, 0.03, 0.10, 0.30)
PAIR_RATIOS = (0.25, 0.50, 0.75)
NEUTRAL_WHITE_LEVELS = (0.0, 0.30, 0.60, 0.80)


@dataclass(frozen=True)
class WorksheetOptions:
    batch_g: float = 10.0
    scale_resolution_g: float = 0.01
    standard_gap_um: float = 150.0
    white_gaps_um: tuple[float, ...] = (75.0, 150.0, 300.0)
    holdout_every: int = 3
    n_neutral_per_level: int = 2
    n_dark: int = 6
    n_random: int = 12
    max_paints: int = 5
    seed: int = 42
    spare_fraction: float = 0.20
    include_pairs: bool = True


@dataclass
class Drawdown:
    """One physical drawdown (one batch of paint, applied with one gap)."""

    drawdown_id: str
    type: SampleType
    components: dict[str, float]  # volume fractions
    gap_um: float
    holdout: bool = False
    group: str = ""
    substrates: tuple[Substrate, ...] = (Substrate.WHITE, Substrate.BLACK)
    masses_g: dict[str, float] = field(default_factory=dict)
    low_mass: list[str] = field(default_factory=list)

    def sample_ids(self) -> list[tuple[str, Substrate, SampleType]]:
        out: list[tuple[str, Substrate, SampleType]] = []
        for sub in self.substrates:
            stype = self.type
            if self.type in (SampleType.MASSTONE_OVER_WHITE, SampleType.MASSTONE_OVER_BLACK):
                stype = (
                    SampleType.MASSTONE_OVER_WHITE
                    if sub == Substrate.WHITE
                    else SampleType.MASSTONE_OVER_BLACK
                )
            if self.type in (SampleType.SUBSTRATE_WHITE, SampleType.SUBSTRATE_BLACK):
                out.append((self.drawdown_id, sub, self.type))
            else:
                out.append((self.drawdown_id + SUFFIX[sub], sub, stype))
        return out

    @property
    def notes(self) -> str:
        tokens = []
        if self.type not in (SampleType.SUBSTRATE_WHITE, SampleType.SUBSTRATE_BLACK):
            tokens.append(f"gap_um={self.gap_um:g}")
        if self.holdout:
            tokens.append("holdout")
        return ";".join(tokens)


@dataclass
class LowMassWarning:
    drawdown_id: str
    paint_id: str
    mass_g: float
    suggested_batch_g: float
    suggest_dilution: bool
    message: str


@dataclass
class WorksheetPlan:
    drawdowns: list[Drawdown]
    totals_g: dict[str, float]  # per paint, including spare
    low_mass: list[LowMassWarning]
    options: WorksheetOptions
    warnings: list[str]

    @property
    def n_rows(self) -> int:
        return sum(len(d.substrates) for d in self.drawdowns)


def _round_percent(fr: np.ndarray, min_fraction: float) -> np.ndarray:
    """Round fractions to whole percent (largest remainder) keeping each >= min_fraction."""
    pct = fr * 100.0
    base = np.floor(pct)
    base = np.maximum(base, round(min_fraction * 100))
    deficit = int(100 - base.sum())
    if deficit > 0:
        order = np.argsort(-(pct - np.floor(pct)))
        for i in range(deficit):
            base[order[i % len(order)]] += 1
    elif deficit < 0:
        order = np.argsort(-base)
        k = 0
        while deficit < 0:
            j = order[k % len(order)]
            if base[j] - 1 >= round(min_fraction * 100):
                base[j] -= 1
                deficit += 1
            k += 1
    return np.asarray(base / 100.0, dtype=np.float64)


def target_masses(
    components: dict[str, float], paints: dict[str, PaintInfo], batch_g: float
) -> dict[str, float]:
    """``m_i = batch * f_i rho_i / sum_j f_j rho_j``."""
    w = {p: f * paints[p].density_g_per_ml for p, f in components.items()}
    tot = sum(w.values())
    return {p: batch_g * v / tot for p, v in w.items()}


def _clean(comps: dict[str, float]) -> dict[str, float]:
    tot = sum(comps.values())
    return {p: round(v / tot, 4) for p, v in comps.items() if v > 0}


def plan_worksheet(
    paints: Sequence[PaintInfo], options: WorksheetOptions | None = None
) -> WorksheetPlan:
    opts = options or WorksheetOptions()
    rng = np.random.default_rng(opts.seed)
    by_id = {p.id: p for p in paints}
    whites = [p for p in paints if p.role == PaintRole.WHITE]
    blacks = [p for p in paints if p.role == PaintRole.BLACK]
    chrom = [p for p in paints if p.role == PaintRole.CHROMATIC]
    warnings: list[str] = []
    if not whites:
        warnings.append("No white paint: tints and white thickness series are skipped.")
    if not blacks:
        warnings.append("No black paint: dark mixtures are skipped.")
    if len(chrom) < 3:
        warnings.append("Fewer than 3 chromatic paints: near-neutral mixtures are skipped.")
    white = whites[0] if whites else None

    dd: list[Drawdown] = [
        Drawdown(
            "SUB-W",
            SampleType.SUBSTRATE_WHITE,
            {},
            0.0,
            group="substrate",
            substrates=(Substrate.WHITE,),
        ),
        Drawdown(
            "SUB-B",
            SampleType.SUBSTRATE_BLACK,
            {},
            0.0,
            group="substrate",
            substrates=(Substrate.BLACK,),
        ),
    ]
    for p in paints:
        if p.role == PaintRole.WHITE:
            for gap in opts.white_gaps_um:
                dd.append(
                    Drawdown(
                        f"MT-{p.id}-{gap:g}",
                        SampleType.MASSTONE_OVER_WHITE,
                        {p.id: 1.0},
                        gap,
                        group="masstone",
                    )
                )
        else:
            dd.append(
                Drawdown(
                    f"MT-{p.id}",
                    SampleType.MASSTONE_OVER_WHITE,
                    {p.id: 1.0},
                    opts.standard_gap_um,
                    group="masstone",
                )
            )
    if white is not None:
        for p in [*chrom, *blacks]:
            levels = BLACK_TINTS if p.role == PaintRole.BLACK else CHROMATIC_TINTS
            for f in levels:
                dd.append(
                    Drawdown(
                        f"TN-{p.id}-{round(f * 100):d}",
                        SampleType.TINT,
                        _clean({p.id: f, white.id: 1.0 - f}),
                        opts.standard_gap_um,
                        group="tint",
                    )
                )

    mixtures: list[Drawdown] = []

    def add_mix(prefix: str, comps: dict[str, float], group: str) -> None:
        mixtures.append(
            Drawdown(
                f"{prefix}", SampleType.MIXTURE, _clean(comps), opts.standard_gap_um, group=group
            )
        )

    if opts.include_pairs:
        for a, b in itertools.combinations(chrom, 2):
            for r in PAIR_RATIOS:
                add_mix(f"PR-{a.id}-{b.id}-{round(r * 100):d}", {a.id: r, b.id: 1 - r}, "pair")
            if white is not None:
                add_mix(f"PW-{a.id}-{b.id}", {a.id: 0.2, b.id: 0.2, white.id: 0.6}, "pair_white")

    k = 0
    if len(chrom) >= 3:
        triples = list(itertools.combinations(range(len(chrom)), 3))
        white_levels: tuple[float, ...] = NEUTRAL_WHITE_LEVELS if white is not None else (0.0,)
        for wl in white_levels:
            for _ in range(opts.n_neutral_per_level):
                tri = triples[int(rng.integers(len(triples)))]
                base = np.full(3, 1 / 3) * rng.uniform(0.7, 1.3, size=3)
                use_black = bool(blacks) and rng.random() < 0.25
                kfrac = 0.05 if use_black else 0.0
                chrom_total = 1.0 - wl - kfrac
                fr = np.concatenate([base / base.sum() * chrom_total, [wl, kfrac]])
                ids = [chrom[i].id for i in tri] + [
                    white.id if white is not None else "",
                    blacks[0].id if blacks else "",
                ]
                fr = _round_percent(fr[fr > 0], 0.01)
                kept = [
                    i
                    for i, v in zip(ids, np.concatenate([base, [wl, kfrac]]), strict=True)
                    if v > 0
                ]
                k += 1
                add_mix(f"NN-{k:03d}", dict(zip(kept, fr.tolist(), strict=True)), "neutral")

    if blacks and len(chrom) >= 2:
        for j in range(opts.n_dark):
            kb = float(rng.uniform(0.10, 0.35))
            n_c = int(rng.integers(2, min(3, len(chrom)) + 1))
            pick = rng.choice(len(chrom), size=n_c, replace=False)
            w = rng.dirichlet(np.ones(n_c)) * (1 - kb)
            fr = _round_percent(np.concatenate([[kb], w]), 0.05)
            ids = [blacks[0].id] + [chrom[i].id for i in pick]
            add_mix(f"DK-{j + 1:03d}", dict(zip(ids, fr.tolist(), strict=True)), "dark")

    others = [p for p in paints if p.role == PaintRole.CHROMATIC]
    max_p = max(3, opts.max_paints)
    for j in range(opts.n_random):
        sel: list[str] = []
        if white is not None and rng.random() < 0.6:
            sel.append(white.id)
        if blacks and rng.random() < 0.3:
            sel.append(blacks[0].id)
        n_total = int(rng.integers(3, max_p + 1))
        n_c = max(1, min(len(others), n_total - len(sel)))
        if others:
            sel += [others[int(i)].id for i in rng.choice(len(others), size=n_c, replace=False)]
        if len(sel) < 2:
            continue
        w = rng.dirichlet(np.ones(len(sel)))
        w = 0.05 + w * (1 - 0.05 * len(sel))
        fr = _round_percent(w, 0.05)
        add_mix(f"RN-{j + 1:03d}", dict(zip(sel, fr.tolist(), strict=True)), "random")

    n = max(1, opts.holdout_every)
    for i, mix in enumerate(mixtures):
        mix.holdout = (i % n) == n - 1
    dd += mixtures

    low: list[LowMassWarning] = []
    totals: dict[str, float] = {p.id: 0.0 for p in paints}
    threshold = opts.scale_resolution_g * 10.0
    for d in dd:
        if not d.components:
            continue
        d.masses_g = target_masses(d.components, by_id, opts.batch_g)
        for pid, m in d.masses_g.items():
            totals[pid] += m
            if m < threshold:
                d.low_mass.append(pid)
                needed = opts.batch_g * threshold / m
                dilute = needed > opts.batch_g * 5
                low.append(
                    LowMassWarning(
                        d.drawdown_id,
                        pid,
                        m,
                        float(np.ceil(needed)),
                        dilute,
                        f"{pid} is {m:.3f} g (< {threshold:g} g = 10 x scale resolution); "
                        + (
                            f"use a diluted stock (e.g. '{by_id[pid].label} 10%') "
                            if dilute
                            else f"increase the batch to >= {np.ceil(needed):.0f} g "
                        )
                        + "for an accurate weighing.",
                    )
                )
    totals = {p: v * (1 + opts.spare_fraction) for p, v in totals.items()}
    return WorksheetPlan(dd, totals, low, opts, warnings)
