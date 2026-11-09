"""Calibration CSV format: parsing and validation.

See ``docs/calibration_format.md`` for the specification. :func:`parse_calibration_csv` never
raises on bad content; it returns every problem as a :class:`ValidationIssue` with the CSV line
number (header = line 1) and column name, so the UI can point at the exact cell.
"""

from __future__ import annotations

import csv
import io
import itertools
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from paintmixer.colorsci.spectral import REQUIRED_RANGE, WAVELENGTHS, resample
from paintmixer.colorsci.types import FloatArray
from paintmixer.domain import PaintInfo, PaintRole

FRACTION_TOLERANCE = 0.002
MASS_DEVIATION_WARN = 0.02  # 2 percentage points
REFLECTANCE_MAX = 1.2
DEFAULT_GAP_UM = 150.0

BASE_COLUMNS = ["sample_id", "type", "substrate", "components", "notes"]
SPECTRUM_COLUMNS = [f"r{int(w)}" for w in WAVELENGTHS]  # canonical: r380 ... r730
SPREAD_COLUMNS = [f"sd{int(w)}" for w in WAVELENGTHS]
# minimum coverage every file must provide: r400 ... r700
REQUIRED_SPECTRUM_COLUMNS = [
    f"r{int(w)}" for w in WAVELENGTHS if REQUIRED_RANGE[0] <= w <= REQUIRED_RANGE[1]
]
OPTIONAL_COLUMNS = ["components_mass_g", "measured_at", "n_readings"]

_SPECTRAL_RE = re.compile(r"^r(\d{3,4})$")
_SPREAD_RE = re.compile(r"^sd(\d{3,4})$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class SampleType(StrEnum):
    SUBSTRATE_WHITE = "substrate_white"
    SUBSTRATE_BLACK = "substrate_black"
    MASSTONE_OVER_WHITE = "masstone_over_white"
    MASSTONE_OVER_BLACK = "masstone_over_black"
    TINT = "tint"
    MIXTURE = "mixture"


class Substrate(StrEnum):
    WHITE = "white"
    BLACK = "black"


_FIXED_SUBSTRATE = {
    SampleType.SUBSTRATE_WHITE: Substrate.WHITE,
    SampleType.SUBSTRATE_BLACK: Substrate.BLACK,
    SampleType.MASSTONE_OVER_WHITE: Substrate.WHITE,
    SampleType.MASSTONE_OVER_BLACK: Substrate.BLACK,
}
SUBSTRATE_IDS = {SampleType.SUBSTRATE_WHITE: "SUB-W", SampleType.SUBSTRATE_BLACK: "SUB-B"}
SUFFIX = {Substrate.WHITE: "-W", Substrate.BLACK: "-B"}
_TYPE_LIST = ", ".join(t.value for t in SampleType)


@dataclass(frozen=True)
class ValidationIssue:
    row: int | None  # CSV line number (header is line 1); None for file-level problems
    column: str | None
    code: str
    message: str
    severity: str = "error"  # "error" | "warning"


@dataclass
class CalibrationSampleData:
    sample_id: str
    type: SampleType
    substrate: Substrate
    components: dict[str, float]  # volume fractions (from masses when given)
    reflectance: FloatArray  # (N_BANDS,)
    gap_um: float | None = None
    holdout: bool = False
    spread: FloatArray | None = None
    planned_components: dict[str, float] | None = None
    masses_g: dict[str, float] | None = None
    measured_at: str | None = None
    n_readings: int | None = None
    notes: str = ""
    line: int = 0

    @property
    def drawdown_id(self) -> str:
        """Identifier shared by the -W / -B rows of one physical drawdown."""
        for suf in SUFFIX.values():
            if self.sample_id.endswith(suf):
                return self.sample_id[: -len(suf)]
        return self.sample_id

    @property
    def effective_gap_um(self) -> float:
        return self.gap_um if self.gap_um is not None else DEFAULT_GAP_UM


@dataclass
class ValidationReport:
    samples: list[CalibrationSampleData] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    wavelengths_in: list[float] = field(default_factory=list)
    n_rows: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def format_components(components: Mapping[str, float], digits: int = 4) -> str:
    return ";".join(f"{pid}:{round(v, digits):g}" for pid, v in components.items())


def _parse_pairs(
    text: str, line: int, column: str, issues: list[ValidationIssue]
) -> dict[str, float] | None:
    out: dict[str, float] = {}
    ok = True
    for raw in text.split(";"):
        token = raw.strip()
        if not token:
            continue
        if token.count(":") != 1:
            issues.append(
                ValidationIssue(
                    line, column, "bad_component", f"expected 'paint_id:value', got {token!r}"
                )
            )
            ok = False
            continue
        pid, val = (t.strip() for t in token.split(":"))
        try:
            v = float(val)
        except ValueError:
            issues.append(
                ValidationIssue(
                    line, column, "bad_component", f"value for {pid!r} is not a number: {val!r}"
                )
            )
            ok = False
            continue
        if not math.isfinite(v) or v < 0:
            issues.append(
                ValidationIssue(
                    line, column, "bad_component", f"value for {pid!r} must be >= 0, got {val}"
                )
            )
            ok = False
            continue
        if pid in out:
            issues.append(
                ValidationIssue(line, column, "duplicate_component", f"paint {pid!r} listed twice")
            )
            ok = False
            continue
        out[pid] = v
    return out if ok else None


def _parse_notes(text: str, line: int, issues: list[ValidationIssue]) -> tuple[float | None, bool]:
    gap: float | None = None
    holdout = False
    for raw in text.split(";"):
        token = raw.strip()
        if not token:
            continue
        if "=" in token:
            key, _, val = (t.strip() for t in token.partition("="))
            if key == "gap_um":
                try:
                    gap = float(val)
                    if not math.isfinite(gap) or gap <= 0:
                        raise ValueError
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            line,
                            "notes",
                            "bad_gap",
                            f"gap_um must be a positive number, got {val!r}",
                        )
                    )
                    gap = None
            else:
                issues.append(
                    ValidationIssue(
                        line,
                        "notes",
                        "unknown_note_key",
                        f"unsupported note key {key!r} ignored",
                        "warning",
                    )
                )
        elif token.lower() == "holdout":
            holdout = True
        # any other bare token is a free-text comment
    return gap, holdout


def _spectral_header(
    header: Sequence[str], issues: list[ValidationIssue]
) -> tuple[list[tuple[int, str, float]], list[tuple[int, str, float]]]:
    spec: list[tuple[int, str, float]] = []
    spread: list[tuple[int, str, float]] = []
    known = set(BASE_COLUMNS) | set(OPTIONAL_COLUMNS)
    for i, name in enumerate(header):
        if name in known:
            continue
        m = _SPECTRAL_RE.match(name)
        if m:
            spec.append((i, name, float(m.group(1))))
            continue
        m = _SPREAD_RE.match(name)
        if m:
            spread.append((i, name, float(m.group(1))))
            continue
        if re.match(r"^[rR]\s*\d", name) or re.match(r"^r\d+\.\d+$", name):
            issues.append(
                ValidationIssue(
                    1,
                    name,
                    "bad_wavelength_header",
                    f"spectral column {name!r} must be 'r' + integer nm, e.g. r400",
                )
            )
        else:
            issues.append(
                ValidationIssue(
                    1, name, "unknown_column", f"unknown column {name!r} ignored", "warning"
                )
            )
    return spec, spread


def _check_grid(
    cols: list[tuple[int, str, float]], issues: list[ValidationIssue], kind: str
) -> bool:
    if not cols:
        if kind == "spectrum":
            issues.append(
                ValidationIssue(
                    1, None, "missing_spectrum", "no spectral columns (need at least r400 ... r700)"
                )
            )
        return kind != "spectrum"
    wl = [c[2] for c in cols]
    names = [c[1] for c in cols]
    ok = True
    if len(set(wl)) != len(wl):
        dup = sorted({n for n, w in zip(names, wl, strict=True) if wl.count(w) > 1})
        issues.append(
            ValidationIssue(
                1, dup[0], "bad_wavelength_header", f"duplicate wavelength columns: {dup}"
            )
        )
        ok = False
    if any(b <= a for a, b in itertools.pairwise(wl)):
        issues.append(
            ValidationIssue(
                1,
                None,
                "bad_wavelength_header",
                f"{kind} columns must be in increasing wavelength order",
            )
        )
        ok = False
    if ok:
        steps = np.diff(wl)
        if steps.size and not np.allclose(steps, steps[0]):
            issues.append(
                ValidationIssue(
                    1, None, "bad_wavelength_header", f"{kind} wavelengths are not evenly spaced"
                )
            )
            ok = False
    if ok and (min(wl) > REQUIRED_RANGE[0] or max(wl) < REQUIRED_RANGE[1]):
        missing = [
            c for c in REQUIRED_SPECTRUM_COLUMNS if float(c[1:]) < min(wl) or float(c[1:]) > max(wl)
        ]
        prefix = "r" if kind == "spectrum" else "sd"
        more = "..." if len(missing) > 4 else ""
        issues.append(
            ValidationIssue(
                1,
                None,
                "bad_wavelength_header",
                f"{kind} covers {min(wl):.0f}-{max(wl):.0f} nm; at least 400-700 nm required "
                f"(missing {', '.join(prefix + m[1:] for m in missing[:4])}{more})",
            )
        )
        ok = False
    return ok


def parse_calibration_csv(
    text: str,
    paints: Mapping[str, PaintInfo] | None = None,
) -> ValidationReport:
    """Parse and validate calibration CSV ``text``.

    ``paints`` maps paint id -> :class:`PaintInfo`; when given, unknown ids are errors and
    densities are used to convert ``components_mass_g``. Rows with errors are excluded from
    ``report.samples``.
    """
    report = ValidationReport()
    issues = report.issues
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    rows = list(reader)
    # skip leading comment lines (starting with '#')
    start = 0
    while start < len(rows) and rows[start] and rows[start][0].lstrip().startswith("#"):
        start += 1
    if start >= len(rows) or not any(c.strip() for c in rows[start]):
        issues.append(ValidationIssue(None, None, "empty_file", "file has no header row"))
        return report
    header_line = start + 1
    header = [h.strip() for h in rows[start]]
    col = {name: i for i, name in enumerate(header)}
    for name in BASE_COLUMNS:
        if name not in col:
            issues.append(
                ValidationIssue(
                    header_line, name, "missing_column", f"required column {name!r} is missing"
                )
            )
    spec_cols, spread_cols = _spectral_header(header, issues)
    grid_ok = _check_grid(spec_cols, issues, "spectrum")
    spread_ok = _check_grid(spread_cols, issues, "spread") if spread_cols else False
    if any(i.row == 1 and i.severity == "error" for i in issues) or not grid_ok:
        # re-label header issues with the real header line
        report.issues = [
            ValidationIssue(
                header_line if i.row == 1 else i.row, i.column, i.code, i.message, i.severity
            )
            for i in issues
        ]
        return report
    wl_in = [c[2] for c in spec_cols]
    report.wavelengths_in = wl_in
    if wl_in != [float(w) for w in WAVELENGTHS]:
        held = wl_in[0] > WAVELENGTHS[0] or wl_in[-1] < WAVELENGTHS[-1]
        issues.append(
            ValidationIssue(
                header_line,
                None,
                "resampled",
                f"spectra on {wl_in[0]:.0f}-{wl_in[-1]:.0f} nm / {len(wl_in)} bands "
                f"are resampled to {WAVELENGTHS[0]:.0f}-{WAVELENGTHS[-1]:.0f} nm / 10 nm"
                + ("; bands outside the measured range are held at the edge value" if held else ""),
                "warning",
            )
        )

    seen_ids: dict[str, int] = {}
    for offset, raw in enumerate(rows[start + 1 :]):
        line = header_line + 1 + offset
        if not raw or not any(c.strip() for c in raw) or raw[0].lstrip().startswith("#"):
            continue
        report.n_rows += 1
        n_err = len([i for i in issues if i.severity == "error"])
        if len(raw) < len(header):
            raw = raw + [""] * (len(header) - len(raw))
        elif len(raw) > len(header) and any(c.strip() for c in raw[len(header) :]):
            issues.append(
                ValidationIssue(
                    line, None, "extra_cells", f"row has {len(raw)} cells, header has {len(header)}"
                )
            )

        def cell(name: str, _raw: list[str] = raw) -> str:
            return _raw[col[name]].strip() if name in col else ""

        sid = cell("sample_id")
        if not sid:
            issues.append(ValidationIssue(line, "sample_id", "missing_value", "sample_id is empty"))
        elif sid in seen_ids:
            issues.append(
                ValidationIssue(
                    line,
                    "sample_id",
                    "duplicate_sample_id",
                    f"{sid!r} already used on line {seen_ids[sid]}",
                )
            )
        else:
            seen_ids[sid] = line

        stype: SampleType | None = None
        try:
            stype = SampleType(cell("type"))
        except ValueError:
            issues.append(
                ValidationIssue(
                    line,
                    "type",
                    "bad_type",
                    f"type {cell('type')!r} must be one of {_TYPE_LIST}",
                )
            )
        substrate: Substrate | None = None
        sub_raw = cell("substrate")
        if stype in _FIXED_SUBSTRATE and not sub_raw:
            substrate = _FIXED_SUBSTRATE[stype]
        else:
            try:
                substrate = Substrate(sub_raw)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        line,
                        "substrate",
                        "bad_substrate",
                        f"substrate {sub_raw!r} must be 'white' or 'black'",
                    )
                )
        if (
            stype in _FIXED_SUBSTRATE
            and substrate is not None
            and substrate != _FIXED_SUBSTRATE[stype]
        ):
            issues.append(
                ValidationIssue(
                    line,
                    "substrate",
                    "substrate_mismatch",
                    f"type {stype.value} requires substrate {_FIXED_SUBSTRATE[stype].value}",
                )
            )
        if stype is not None and substrate is not None and sid:
            if stype in SUBSTRATE_IDS and sid != SUBSTRATE_IDS[stype]:
                issues.append(
                    ValidationIssue(
                        line,
                        "sample_id",
                        "bad_sample_id",
                        f"{stype.value} rows must use sample_id {SUBSTRATE_IDS[stype]}",
                        "warning",
                    )
                )
            elif stype in (SampleType.TINT, SampleType.MIXTURE) and not sid.endswith(
                SUFFIX[substrate]
            ):
                issues.append(
                    ValidationIssue(
                        line,
                        "sample_id",
                        "bad_sample_id",
                        f"{stype.value} on {substrate.value} must end with {SUFFIX[substrate]}",
                    )
                )

        # components
        comp_raw = cell("components")
        comps: dict[str, float] | None = _parse_pairs(comp_raw, line, "components", issues)
        if stype in SUBSTRATE_IDS:
            if comps:
                issues.append(
                    ValidationIssue(
                        line,
                        "components",
                        "unexpected_components",
                        "substrate rows must have empty components",
                    )
                )
            comps = {}
        elif comps is not None:
            if not comps:
                issues.append(
                    ValidationIssue(line, "components", "missing_value", "components are required")
                )
                comps = None
            else:
                total = sum(comps.values())
                if abs(total - 1.0) > FRACTION_TOLERANCE:
                    issues.append(
                        ValidationIssue(
                            line,
                            "components",
                            "fractions_sum",
                            f"fractions sum to {total:.4f}, expected 1 (±{FRACTION_TOLERANCE})",
                        )
                    )
                if paints is not None:
                    for pid in comps:
                        if pid not in paints:
                            issues.append(
                                ValidationIssue(
                                    line, "components", "unknown_paint", f"unknown paint id {pid!r}"
                                )
                            )
                if (
                    stype in (SampleType.MASSTONE_OVER_WHITE, SampleType.MASSTONE_OVER_BLACK)
                    and len(comps) != 1
                ):
                    issues.append(
                        ValidationIssue(
                            line,
                            "components",
                            "bad_masstone",
                            "masstones must contain exactly one paint at 1.0",
                        )
                    )
                if stype == SampleType.TINT:
                    if len(comps) != 2:
                        issues.append(
                            ValidationIssue(
                                line,
                                "components",
                                "bad_tint",
                                "tints must contain exactly two paints (one white)",
                            )
                        )
                    elif (
                        paints is not None
                        and all(p in paints for p in comps)
                        and not any(paints[p].role == PaintRole.WHITE for p in comps)
                    ):
                        issues.append(
                            ValidationIssue(
                                line,
                                "components",
                                "bad_tint",
                                "tints must include a white paint",
                                "warning",
                            )
                        )

        masses: dict[str, float] | None = None
        planned = comps
        if "components_mass_g" in col and cell("components_mass_g"):
            masses = _parse_pairs(cell("components_mass_g"), line, "components_mass_g", issues)
            if masses is not None and paints is not None:
                unknown = [p for p in masses if p not in paints]
                for pid in unknown:
                    issues.append(
                        ValidationIssue(
                            line, "components_mass_g", "unknown_paint", f"unknown paint id {pid!r}"
                        )
                    )
                total_mass = sum(masses.values())
                if not unknown and total_mass > 0:
                    vols = {p: m / paints[p].density_g_per_ml for p, m in masses.items()}
                    vtot = sum(vols.values())
                    from_mass = {p: v / vtot for p, v in vols.items()}
                    if comps:
                        keys = set(comps) | set(from_mass)
                        dev = max(abs(comps.get(k, 0.0) - from_mass.get(k, 0.0)) for k in keys)
                        if dev > MASS_DEVIATION_WARN:
                            issues.append(
                                ValidationIssue(
                                    line,
                                    "components_mass_g",
                                    "mass_deviation",
                                    "weighed masses give fractions "
                                    f"{format_components(from_mass, 3)}, {dev * 100:.1f} pp "
                                    f"from planned {format_components(comps, 3)}",
                                    "warning",
                                )
                            )
                    comps = from_mass
                elif total_mass <= 0:
                    issues.append(
                        ValidationIssue(
                            line, "components_mass_g", "bad_component", "masses sum to zero"
                        )
                    )

        gap, holdout = _parse_notes(cell("notes"), line, issues)
        if holdout and stype not in (SampleType.MIXTURE, SampleType.TINT):
            issues.append(
                ValidationIssue(
                    line,
                    "notes",
                    "holdout_ignored",
                    "holdout only applies to mixtures and tints",
                    "warning",
                )
            )
            holdout = False

        # spectrum
        values = np.full(len(spec_cols), np.nan)
        for j, (ci, name, _) in enumerate(spec_cols):
            s = raw[ci].strip() if ci < len(raw) else ""
            if not s:
                issues.append(
                    ValidationIssue(line, name, "missing_value", "spectrum value is empty")
                )
                continue
            try:
                v = float(s)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        line, name, "not_numeric", f"spectrum value {s!r} is not a number"
                    )
                )
                continue
            if not math.isfinite(v) or v < 0 or v > REFLECTANCE_MAX:
                hint = " (values look like percent; use 0-1)" if 1.2 < v <= 120 else ""
                issues.append(
                    ValidationIssue(
                        line,
                        name,
                        "out_of_range",
                        f"reflectance {v} outside 0-{REFLECTANCE_MAX}{hint}",
                    )
                )
                continue
            values[j] = v
        spread_vals: FloatArray | None = None
        if spread_ok:
            sv = np.full(len(spread_cols), np.nan)
            for j, (ci, name, _) in enumerate(spread_cols):
                s = raw[ci].strip() if ci < len(raw) else ""
                if not s:
                    continue
                try:
                    sv[j] = float(s)
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            line, name, "not_numeric", f"spread value {s!r} is not a number"
                        )
                    )
            if np.all(np.isfinite(sv)):
                spread_vals = resample([c[2] for c in spread_cols], sv)

        measured_at = cell("measured_at") or None
        n_readings: int | None = None
        if cell("n_readings"):
            try:
                n_readings = int(cell("n_readings"))
            except ValueError:
                issues.append(
                    ValidationIssue(
                        line, "n_readings", "not_numeric", "n_readings must be an integer"
                    )
                )

        n_err_now = len([i for i in issues if i.severity == "error"])
        if n_err_now == n_err and stype is not None and substrate is not None and comps is not None:
            report.samples.append(
                CalibrationSampleData(
                    sample_id=sid,
                    type=stype,
                    substrate=substrate,
                    components=comps,
                    reflectance=resample(wl_in, values),
                    gap_um=gap,
                    holdout=holdout,
                    spread=spread_vals,
                    planned_components=planned if masses else None,
                    masses_g=masses,
                    measured_at=measured_at,
                    n_readings=n_readings,
                    notes=cell("notes"),
                    line=line,
                )
            )

    if report.n_rows == 0:
        issues.append(
            ValidationIssue(None, None, "empty_file", "file has a header but no data rows")
        )
    _check_pairs(report)
    return report


def _check_pairs(report: ValidationReport) -> None:
    """Warn when a tint/mixture drawdown is missing its -W or -B counterpart."""
    by_drawdown: dict[str, set[Substrate]] = {}
    lines: dict[str, int] = {}
    for s in report.samples:
        if s.type in (SampleType.TINT, SampleType.MIXTURE):
            by_drawdown.setdefault(s.drawdown_id, set()).add(s.substrate)
            lines.setdefault(s.drawdown_id, s.line)
    for d, subs in by_drawdown.items():
        if len(subs) == 1:
            missing = next(iter({Substrate.WHITE, Substrate.BLACK} - subs))
            report.issues.append(
                ValidationIssue(
                    lines[d],
                    "sample_id",
                    "missing_pair",
                    f"drawdown {d!r} has no {missing.value}-background row ({d}{SUFFIX[missing]})",
                    "warning",
                )
            )


def write_calibration_csv(
    samples: Sequence[CalibrationSampleData],
    *,
    include_spread: bool = False,
    include_masses: bool = False,
    digits: int = 5,
) -> str:
    """Serialise samples back to the CSV format (spectra on the canonical grid)."""
    header = list(BASE_COLUMNS)
    if include_masses:
        header.append("components_mass_g")
    with_meta = any(s.n_readings or s.measured_at for s in samples)
    if with_meta:
        header += ["measured_at", "n_readings"]
    header += SPECTRUM_COLUMNS
    if include_spread:
        header += SPREAD_COLUMNS
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for s in samples:
        notes = [t for t in s.notes.split(";") if t.strip()] if s.notes else []
        if not notes:
            if s.gap_um is not None:
                notes.append(f"gap_um={s.gap_um:g}")
            if s.holdout:
                notes.append("holdout")
        comps = s.planned_components if (include_masses and s.planned_components) else s.components
        row: list[str] = [
            s.sample_id,
            s.type.value,
            s.substrate.value,
            format_components(comps),
            ";".join(notes),
        ]
        if include_masses:
            row.append(format_components(s.masses_g or {}, 3))
        if with_meta:
            row += [s.measured_at or "", str(s.n_readings) if s.n_readings else ""]
        row += [f"{v:.{digits}f}" for v in s.reflectance]
        if include_spread:
            sp = s.spread if s.spread is not None else np.zeros(len(WAVELENGTHS))
            row += [f"{v:.{digits}f}" for v in sp]
        w.writerow(row)
    return buf.getvalue()


def sample_id_is_slug(paint_id: str) -> bool:
    return bool(_ID_RE.match(paint_id))
