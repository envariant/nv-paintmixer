"""Per-paint calibration coverage and accuracy.

Coverage is the fit's own data requirement per paint (also behind the fit's data warnings):
a masstone, a tint with white for every non-white paint, and at least
:data:`MIN_MIXTURE_DRAWDOWNS` mixture drawdowns in the training set.

Accuracy is taken from a fitted model's residuals: the dE2000 of every sample that contains the
paint. Hold-out samples are preferred because the fit did not see them; training residuals are
used only when a paint has no hold-out sample.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from paintmixer.calibration.format import CalibrationSampleData, SampleType
from paintmixer.colorsci.types import ArrayLike
from paintmixer.domain import PaintRole

MIN_MIXTURE_DRAWDOWNS = 3
# An under-sampled paint's error estimate rests on too few samples to trust; it is doubled.
UNDER_SAMPLED_FACTOR = 2.0

_MASSTONES = (SampleType.MASSTONE_OVER_WHITE, SampleType.MASSTONE_OVER_BLACK)


@dataclass(frozen=True)
class PaintCoverage:
    has_masstone: bool
    has_tint: bool | None  # None: not required (white, or no white in the set)
    n_mixture_drawdowns: int

    @property
    def ok(self) -> bool:
        return (
            self.has_masstone
            and self.has_tint is not False
            and self.n_mixture_drawdowns >= MIN_MIXTURE_DRAWDOWNS
        )


def paint_coverage(
    samples: Sequence[CalibrationSampleData],
    paint_ids: Sequence[str],
    roles: Mapping[str, PaintRole],
    white: str | None,
) -> dict[str, PaintCoverage]:
    mixtures = [s for s in samples if s.type == SampleType.MIXTURE and not s.holdout]
    out = {}
    for pid in paint_ids:
        has_mt = any(s.type in _MASSTONES and list(s.components) == [pid] for s in samples)
        has_tint: bool | None = None
        if roles.get(pid) != PaintRole.WHITE and white is not None:
            has_tint = any(
                s.type == SampleType.TINT and pid in s.components and white in s.components
                for s in samples
            )
        n_mix = len({s.drawdown_id for s in mixtures if pid in s.components})
        out[pid] = PaintCoverage(has_mt, has_tint, n_mix)
    return out


@dataclass(frozen=True)
class SampleError:
    sample_id: str
    de2000: float
    holdout: bool
    outlier: bool
    major: bool = True  # the paint is a big part of this sample (see is_major); used for review


MAJOR_FRACTION = 0.25


def is_major(sample: CalibrationSampleData, pid: str, roles: Mapping[str, PaintRole]) -> bool:
    """Whether ``pid`` is a big part of ``sample``, so the sample's error says something about
    that paint: masstones of the paint, tints of the paint (not of the white it is let down
    with), and mixtures where it is at least :data:`MAJOR_FRACTION` of the volume."""
    if sample.type in _MASSTONES:
        return True
    if sample.type == SampleType.TINT:
        return roles.get(pid) != PaintRole.WHITE
    total = sum(sample.components.values())
    return total > 0 and sample.components.get(pid, 0.0) / total >= MAJOR_FRACTION


@dataclass(frozen=True)
class PaintQuality:
    paint_id: str
    coverage: PaintCoverage
    samples: list[SampleError] = field(default_factory=list)

    @property
    def median_de(self) -> float | None:
        d = [s.de2000 for s in self.samples]
        return float(np.median(d)) if d else None

    @property
    def holdout_rms_de(self) -> float | None:
        h = [s.de2000 for s in self.samples if s.holdout]
        return float(np.sqrt(np.mean(np.square(h)))) if h else None

    @property
    def rms_de(self) -> float | None:
        d = [s.de2000 for s in self.samples]
        return float(np.sqrt(np.mean(np.square(d)))) if d else None

    @property
    def error_de(self) -> float | None:
        """Typical prediction error (dE2000) of mixtures with this paint: hold-out RMS (else
        training RMS), doubled when the paint is below its sample requirement."""
        base = self.holdout_rms_de
        if base is None:
            base = self.rms_de
        if base is None:
            return None
        return base * (1.0 if self.coverage.ok else UNDER_SAMPLED_FACTOR)


def paint_quality(
    residuals: Sequence[Mapping[str, Any]],
    samples: Mapping[str, CalibrationSampleData],
    paint_ids: Sequence[str],
    roles: Mapping[str, PaintRole],
    white: str | None,
) -> dict[str, PaintQuality]:
    """Per-paint coverage and residuals of a fit.

    ``residuals`` are the model's stored residual records (``sample_id``, ``de2000``,
    ``holdout``, ``outlier``); ``samples`` maps sample ids to the calibration samples, which
    give each residual its paints. Residuals of samples no longer stored are skipped.
    """
    used = [samples[r["sample_id"]] for r in residuals if r["sample_id"] in samples]
    coverage = paint_coverage(used, paint_ids, roles, white)
    per: dict[str, list[SampleError]] = {pid: [] for pid in paint_ids}
    for r in residuals:
        s = samples.get(r["sample_id"])
        if s is None:
            continue
        for pid in s.components:
            if pid in per:
                per[pid].append(
                    SampleError(
                        r["sample_id"],
                        float(r["de2000"]),
                        bool(r["holdout"]),
                        bool(r["outlier"]),
                        is_major(s, pid, roles),
                    )
                )
    return {pid: PaintQuality(pid, coverage[pid], per[pid]) for pid in paint_ids}


Grade = Literal["excellent", "good", "fair", "poor"]
Status = Literal["ok", "review", "needs_samples", "stale", "uncalibrated"]

# median dE2000 below each bound earns the grade
GRADE_BOUNDS: tuple[tuple[float, Grade], ...] = ((0.4, "excellent"), (1.0, "good"), (2.0, "fair"))
REVIEW_DE = 2.0  # any sample at or above this asks for a review


def grade(median_de: float) -> Grade:
    return next((g for bound, g in GRADE_BOUNDS if median_de < bound), "poor")


def paint_status(q: PaintQuality | None, batch_changed: bool) -> Status:
    """One status per paint, the most pressing first: ``uncalibrated`` (no samples in the fit,
    e.g. a swatch model), ``stale`` (its batch changed since the fit, so the model may no longer
    describe it), ``needs_samples`` (below the fit's sample requirement), ``review`` (a sample
    the paint is a big part of, at or above :data:`REVIEW_DE`), else ``ok``."""
    if q is None or not q.samples:
        return "uncalibrated"
    if batch_changed:
        return "stale"
    if not q.coverage.ok:
        return "needs_samples"
    if any(s.de2000 >= REVIEW_DE and s.major for s in q.samples):
        return "review"
    return "ok"


def mix_uncertainty(
    fractions: ArrayLike,
    errors: ArrayLike,
    dose_sensitivity: float,
    dose_error_pct: float,
) -> float:
    """Expected dE2000 spread of a mix: the fraction-weighted RMS of its paints' errors,
    combined (root sum of squares) with the dosing error, i.e. the recipe's dose sensitivity
    (dE per 1 % overdose) times the dispenser's dose error in % of the batch."""
    f = np.asarray(fractions, dtype=np.float64)
    e = np.asarray(errors, dtype=np.float64)
    model = float(np.sum(f / f.sum() * e**2))
    dose = (dose_sensitivity * dose_error_pct) ** 2
    return float(np.sqrt(model + dose))
