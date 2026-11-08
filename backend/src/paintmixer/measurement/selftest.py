"""Instrument self-test (``paintmixer measure selftest``).

Steps, each with an explicit operator prompt (nothing is assumed from earlier runs):

1. instrument detection via ``spotread -?`` (see :func:`spotread.detect_instruments`; done by the
   CLI before a spotread source is opened);
2. white calibration on the instrument's base tile (the source's own calibration prompt);
3. ``n`` readings of a white tile, optionally lifting and replacing the instrument in between;
4. statistics: per-band mean/std, repeatability (dE2000 of each reading vs the mean spectrum,
   D65 / CIE 1931 2°), drift (dE2000 between the mean of the first and last third of readings,
   plus the per-reading slope), and sanity checks on the white spectrum;
5. optional reference check on matte white, mid-grey and matte black;
6. a PASS / WARN / FAIL verdict from :class:`SelftestThresholds`.

All colour maths goes through :mod:`paintmixer.colorsci`; readings come from any
:class:`~paintmixer.measurement.base.MeasurementSource`.
"""

from __future__ import annotations

import csv
import itertools
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from paintmixer.calibration.format import SPECTRUM_COLUMNS, Substrate
from paintmixer.colorsci.convert import lab_to_lch, reflectance_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.spectral import WAVELENGTHS
from paintmixer.colorsci.types import FloatArray
from paintmixer.measurement.base import MeasurementSource, MeasureRequest, Reading

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}

TILE_ID = "WHITE-TILE"
REFERENCES: tuple[tuple[str, str], ...] = (
    ("REF-WHITE", "matte white"),
    ("REF-GREY", "mid-grey"),
    ("REF-BLACK", "matte black"),
)


@dataclass(frozen=True)
class SelftestThresholds:
    """Verdict thresholds. Defaults are PaintMixer's working guesses, not manufacturer figures
    (see docs/ASSUMPTIONS.md); they are editable in the app settings."""

    warn_de: float = 0.5  # max dE2000 of a reading vs the mean (also used for drift)
    fail_de: float = 1.0
    white_min: float = 0.60  # plausible white-tile reflectance, every band 400-700 nm
    white_max: float = 1.05
    max_band_jump: float = 0.05  # largest allowed step between adjacent 10 nm bands
    smoothness_rms: float = 0.01  # RMS second difference of the mean spectrum
    cast_chroma: float = 3.0  # C*ab above which a neutral reference has a colour cast
    min_readings: int = 3


@dataclass
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    value: float | None
    threshold: str
    message: str


@dataclass
class ReferenceResult:
    sample_id: str
    label: str
    lab: list[float]
    L: float
    chroma: float
    hue_deg: float
    repeat_de_max: float


@dataclass
class SelftestReport:
    started_at: str
    finished_at: str
    source: str
    instrument: str | None
    n: int
    replace: bool
    thresholds: SelftestThresholds
    wavelengths: list[float]
    mean: list[float]
    std: list[float]
    lab_mean: list[float]
    de_vs_mean: list[float]
    repeat_mean_de: float
    repeat_max_de: float
    drift_de: float
    drift_slope_de_per_reading: float
    checks: list[Check]
    references: list[ReferenceResult] = field(default_factory=list)
    verdict: str = PASS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- analysis (pure) ------------------------------------------------------------------------


def _check(name: str, bad: bool, warn_only: bool, value: float | None, thr: str, msg: str) -> Check:
    status = PASS if not bad else (WARN if warn_only else FAIL)
    return Check(name, status, value, thr, msg)


def _graded(name: str, value: float, warn: float, fail: float, what: str) -> Check:
    status = FAIL if value > fail else WARN if value > warn else PASS
    return Check(name, status, value, f"warn > {warn:g}, fail > {fail:g}", f"{what} {value:.3f}")


def analyse_tile(
    readings: FloatArray, thresholds: SelftestThresholds
) -> tuple[dict[str, Any], list[Check]]:
    """Statistics and checks for ``readings`` (n, 31) of a white tile."""
    t = thresholds
    r = np.asarray(readings, dtype=np.float64)
    n = r.shape[0]
    if n < t.min_readings:
        raise ValueError(f"need at least {t.min_readings} readings, got {n}")
    mean = r.mean(axis=0)
    std = r.std(axis=0, ddof=1)
    lab = reflectance_to_lab(r)
    lab_mean = reflectance_to_lab(mean)
    de = delta_e_2000(lab, lab_mean[None, :])
    k = max(1, n // 3)
    first, last = r[:k].mean(axis=0), r[-k:].mean(axis=0)
    lab_first = reflectance_to_lab(first)
    drift = float(delta_e_2000(reflectance_to_lab(last), lab_first))
    de_vs_first = delta_e_2000(lab, lab_first[None, :])
    slope = float(np.polyfit(np.arange(n), de_vs_first, 1)[0]) if n > 1 else 0.0

    jumps = np.abs(np.diff(mean))
    j_max = int(np.argmax(jumps))
    d2 = mean[:-2] - 2.0 * mean[1:-1] + mean[2:]
    rough = float(np.sqrt(np.mean(d2**2)))
    n_neg = int((r < 0).sum())
    lo, hi = float(mean.min()), float(mean.max())
    checks = [
        _graded(
            "repeatability",
            float(de.max()),
            t.warn_de,
            t.fail_de,
            "max dE2000 of a reading vs the mean spectrum",
        ),
        _graded(
            "drift",
            drift,
            t.warn_de,
            t.fail_de,
            f"dE2000 between the first and last {k} reading(s)",
        ),
        _check(
            "negative_values",
            n_neg > 0,
            False,
            float(n_neg),
            "none allowed",
            f"{n_neg} negative band value(s) across all readings",
        ),
        _check(
            "white_range",
            lo < t.white_min or hi > t.white_max,
            False,
            lo,
            f"{t.white_min:g}-{t.white_max:g} in every band",
            f"mean reflectance spans {lo:.3f}-{hi:.3f} over 400-700 nm"
            + (" (not a plausible white tile)" if lo < t.white_min or hi > t.white_max else ""),
        ),
        _check(
            "band_jumps",
            float(jumps.max()) > t.max_band_jump,
            False,
            float(jumps.max()),
            f"<= {t.max_band_jump:g}",
            f"largest adjacent-band step {jumps.max():.4f} at "
            f"{WAVELENGTHS[j_max]:.0f}-{WAVELENGTHS[j_max + 1]:.0f} nm",
        ),
        _check(
            "smoothness",
            rough > t.smoothness_rms,
            True,
            rough,
            f"<= {t.smoothness_rms:g}",
            f"RMS second difference {rough:.4f}",
        ),
    ]
    stats = {
        "mean": mean,
        "std": std,
        "lab_mean": lab_mean,
        "de": de,
        "drift": drift,
        "slope": slope,
    }
    return stats, checks


def analyse_references(
    spectra: dict[str, FloatArray], thresholds: SelftestThresholds
) -> tuple[list[ReferenceResult], list[Check]]:
    """L*, chroma and casts of the white/grey/black references (each ``(m, 31)`` readings)."""
    labels = dict(REFERENCES)
    out: list[ReferenceResult] = []
    checks: list[Check] = []
    for sid, reads in spectra.items():
        r = np.asarray(reads, dtype=np.float64)
        mean = r.mean(axis=0)
        lab = reflectance_to_lab(mean)
        lch = lab_to_lch(lab)
        rep = float(delta_e_2000(reflectance_to_lab(r), lab[None, :]).max()) if len(r) > 1 else 0.0
        res = ReferenceResult(
            sid,
            labels.get(sid, sid),
            [float(x) for x in lab],
            float(lch[0]),
            float(lch[1]),
            float(lch[2]),
            rep,
        )
        out.append(res)
        cast = res.chroma > thresholds.cast_chroma
        checks.append(
            _check(
                f"cast_{sid}",
                cast,
                True,
                res.chroma,
                f"C* <= {thresholds.cast_chroma:g}",
                f"{res.label}: L* {res.L:.1f}, C* {res.chroma:.2f}"
                + (f" - colour cast towards hue {res.hue_deg:.0f}°" if cast else ""),
            )
        )
        n_neg = int((r < 0).sum())
        if n_neg:
            checks.append(
                Check(
                    f"negative_{sid}",
                    FAIL,
                    float(n_neg),
                    "none allowed",
                    f"{res.label}: {n_neg} negative band value(s)",
                )
            )
    order = [x for x in out if x.sample_id in labels]
    order.sort(key=lambda x: [s for s, _ in REFERENCES].index(x.sample_id))
    Ls = [x.L for x in order]
    if len(Ls) >= 2:
        mono = all(a > b for a, b in itertools.pairwise(Ls))
        checks.append(
            _check(
                "lightness_order",
                not mono,
                False,
                None,
                "white > grey > black",
                "L* "
                + " > ".join(f"{x.label} {x.L:.1f}" for x in order)
                + ("" if mono else " is not in descending order (swapped references?)"),
            )
        )
    return out, checks


def verdict(checks: list[Check]) -> str:
    worst = max((_RANK[c.status] for c in checks), default=0)
    return {0: PASS, 1: WARN, 2: FAIL}[worst]


# --- orchestration --------------------------------------------------------------------------


Ask = Callable[[str], str]
Say = Callable[[str], None]


@dataclass
class SelftestRun:
    report: SelftestReport
    tile_readings: list[Reading]
    reference_readings: dict[str, list[Reading]]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_selftest(
    source: MeasurementSource,
    *,
    n: int = 10,
    replace: bool = False,
    reference_check: bool = False,
    reference_readings: int = 3,
    thresholds: SelftestThresholds | None = None,
    ask: Ask = input,
    say: Say = print,
    instrument: str | None = None,
    reference_requests: dict[str, MeasureRequest] | None = None,
) -> SelftestRun:
    """Guide the operator through the self-test and return the report and raw readings.

    ``reference_requests`` lets simulators know what each reference is; real instruments only
    use the sample id.
    """
    t = thresholds or SelftestThresholds()
    if n < t.min_readings:
        raise ValueError(f"--n must be at least {t.min_readings} (drift compares thirds)")
    started = _now()
    say("Step 1/4 - white calibration")
    ask(
        "Place the instrument on its white calibration (base) tile - ColorMunki: turn the dial to "
        "the calibration position, then press Enter to calibrate"
    )
    source.open()
    try:
        say("Calibration done.")
        say(f"Step 2/4 - {n} readings of the white tile")
        ask(
            "Set the instrument to measurement mode and place it flat on the white tile. "
            "Press Enter to start"
        )
        tile: list[Reading] = []
        req = MeasureRequest(TILE_ID, Substrate.WHITE)
        for i in range(n):
            if replace and i > 0:
                ask(
                    f"Lift the instrument off the tile and place it back ({i + 1}/{n}), "
                    "then press Enter"
                )
            tile.append(source.read(req))
            say(f"  reading {i + 1}/{n} done")
        refs: dict[str, list[Reading]] = {}
        if reference_check:
            say("Step 3/4 - reference check")
            for sid, label in REFERENCES:
                ask(f"Place the instrument on the {label} reference ({sid}), then press Enter")
                rq = (reference_requests or {}).get(sid, MeasureRequest(sid))
                refs[sid] = [source.read(rq) for _ in range(reference_readings)]
                say(f"  {label}: {reference_readings} reading(s) done")
        else:
            say("Step 3/4 - reference check skipped (use --reference-check)")
    finally:
        source.close()
    say("Step 4/4 - analysis")
    R = np.stack([x.reflectance for x in tile])
    stats, checks = analyse_tile(R, t)
    ref_results: list[ReferenceResult] = []
    if refs:
        ref_results, ref_checks = analyse_references(
            {k: np.stack([x.reflectance for x in v]) for k, v in refs.items()}, t
        )
        checks += ref_checks
    report = SelftestReport(
        started_at=started,
        finished_at=_now(),
        source=source.name,
        instrument=instrument,
        n=n,
        replace=replace,
        thresholds=t,
        wavelengths=WAVELENGTHS.tolist(),
        mean=[float(x) for x in stats["mean"]],
        std=[float(x) for x in stats["std"]],
        lab_mean=[float(x) for x in stats["lab_mean"]],
        de_vs_mean=[float(x) for x in stats["de"]],
        repeat_mean_de=float(stats["de"].mean()),
        repeat_max_de=float(stats["de"].max()),
        drift_de=float(stats["drift"]),
        drift_slope_de_per_reading=float(stats["slope"]),
        checks=checks,
        references=ref_results,
        verdict=verdict(checks),
    )
    return SelftestRun(report, tile, refs)


# --- output ---------------------------------------------------------------------------------


def format_report(r: SelftestReport) -> str:
    lines = [
        f"PaintMixer instrument self-test - {r.verdict}",
        f"source {r.source}"
        + (f", instrument {r.instrument}" if r.instrument else "")
        + f", {r.n} readings"
        + (" (lifted and replaced between readings)" if r.replace else ""),
        f"started {r.started_at}, finished {r.finished_at}",
        "",
        "White tile, per band (reflectance 0-1):",
        "   nm    mean     std    |    nm    mean     std",
    ]
    half = (len(r.wavelengths) + 1) // 2
    for i in range(half):
        left = f"  {r.wavelengths[i]:4.0f}  {r.mean[i]:.4f}  {r.std[i]:.5f}"
        j = i + half
        right = (
            f"   {r.wavelengths[j]:4.0f}  {r.mean[j]:.4f}  {r.std[j]:.5f}"
            if j < len(r.wavelengths)
            else ""
        )
        lines.append(left + "  |" + right)
    L, a, b = r.lab_mean
    lines += [
        "",
        f"Mean Lab (D65/2°): L* {L:.2f}  a* {a:.2f}  b* {b:.2f}",
        f"Repeatability vs mean: mean dE2000 {r.repeat_mean_de:.3f}, max {r.repeat_max_de:.3f}",
        f"Drift: dE2000 first vs last third {r.drift_de:.3f} "
        f"(trend {r.drift_slope_de_per_reading:+.4f} dE per reading)",
    ]
    if r.references:
        lines += ["", "References:"]
        for ref in r.references:
            lines.append(
                f"  {ref.label:12s} L* {ref.L:6.2f}  C* {ref.chroma:5.2f}  h {ref.hue_deg:5.1f}°"
                f"  (repeat max dE2000 {ref.repeat_de_max:.2f})"
            )
    lines += ["", "Checks:"]
    for c in r.checks:
        lines.append(f"  [{c.status}] {c.name}: {c.message} ({c.threshold})")
    lines += ["", f"Verdict: {r.verdict}"]
    return "\n".join(lines)


def default_output_root(start: Path | None = None) -> Path:
    """``<repo>/sample_data/selftests`` when run inside the repo, else ``./selftests``."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "sample_data").is_dir():
            return d / "sample_data" / "selftests"
    return here / "selftests"


def write_outputs(run: SelftestRun, root: Path) -> Path:
    """Write ``report.json``, ``spectra.csv`` (400-700 nm) and, when the instrument reported
    another grid, ``spectra_raw.csv``, into ``root/<UTC timestamp>/``."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = root / stamp
    k = 1
    while out.exists():
        out = root / f"{stamp}-{k}"
        k += 1
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(run.report.to_dict(), indent=1) + "\n")

    rows: list[tuple[str, int, Reading]] = [
        (TILE_ID, i, x) for i, x in enumerate(run.tile_readings)
    ]
    for sid, reads in run.reference_readings.items():
        rows += [(sid, i, x) for i, x in enumerate(reads)]
    with (out / "spectra.csv").open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sample_id", "reading", "taken_at", "source", *SPECTRUM_COLUMNS])
        for sid, i, x in rows:
            w.writerow([sid, i + 1, x.taken_at, x.source, *(f"{v:.6f}" for v in x.reflectance)])
    grids = {x.wavelengths_in for _, _, x in rows}
    if len(grids) == 1 and next(iter(grids)) and rows[0][2].raw:
        wl = next(iter(grids))
        with (out / "spectra_raw.csv").open("w", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["sample_id", "reading", *(f"r{v:.0f}" for v in wl)])
            for sid, i, x in rows:
                w.writerow([sid, i + 1, *(f"{v:g}" for v in x.raw)])
    return out
