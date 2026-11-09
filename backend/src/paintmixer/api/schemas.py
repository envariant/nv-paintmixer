"""Pydantic request/response models for the public API (``/api/v1``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paintmixer.colorsci.spectral import N_BANDS, Illuminant
from paintmixer.domain import PaintRole

SLUG = r"^[a-z0-9][a-z0-9_.-]*$"
HEX_PATTERN = r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"
Spectrum = list[float]


class _Model(BaseModel):
    """Request bodies: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    """Responses: built from DB rows, extra attributes are ignored."""

    model_config = ConfigDict(extra="ignore")


# --- paints ---------------------------------------------------------------------------------


class PaintFields(_Model):
    name: str = Field(min_length=1, max_length=120)
    brand: str = ""
    pigment_code: str = ""
    role: PaintRole = PaintRole.CHROMATIC
    density_g_per_ml: float = Field(1.0, gt=0, le=10)
    cost_per_ml: float = Field(0.0, ge=0, description="Cost per ml in the configured currency")
    min_dose_ml: float = Field(0.0, ge=0)
    dispenser_channel: int | None = Field(None, ge=1)
    loaded: bool = Field(False, description="Currently on the dispensing machine")
    parent_paint_id: str | None = Field(None, description="Parent paint for a diluted stock")
    dilution: float | None = Field(None, gt=0, lt=1, description="Fraction of parent in the stock")
    active: bool = True
    notes: str = ""
    swatch_hex: str | None = Field(
        None, pattern=HEX_PATTERN, description="Masstone swatch colour (for the uncalibrated model)"
    )
    tint_hex: str | None = Field(
        None, pattern=HEX_PATTERN, description="Tint swatch colour: the paint reduced with white"
    )
    tint_fraction: float | None = Field(
        None, gt=0, lt=1, description="Paint volume fraction in the tint swatch (default 0.1)"
    )


class PaintCreate(PaintFields):
    id: str = Field(min_length=1, max_length=64, pattern=SLUG)


class PaintUpdate(_Model):
    name: str | None = Field(None, min_length=1, max_length=120)
    brand: str | None = None
    pigment_code: str | None = None
    role: PaintRole | None = None
    density_g_per_ml: float | None = Field(None, gt=0, le=10)
    cost_per_ml: float | None = Field(None, ge=0)
    min_dose_ml: float | None = Field(None, ge=0)
    dispenser_channel: int | None = Field(None, ge=1)
    loaded: bool | None = None
    parent_paint_id: str | None = None
    dilution: float | None = Field(None, gt=0, lt=1)
    active: bool | None = None
    notes: str | None = None
    swatch_hex: str | None = Field(None, pattern=HEX_PATTERN)
    tint_hex: str | None = Field(None, pattern=HEX_PATTERN)
    tint_fraction: float | None = Field(None, gt=0, lt=1)


class PaintRead(PaintFields):
    model_config = ConfigDict(extra="ignore")

    id: str
    calibrated: bool = Field(False, description="Present in the active fitted model")
    tinting_strength: float | None = Field(
        None,
        description="K/S of a 10 % reduction in the model's white at its absorption peak "
        "(ISO 787-24 style; active model). None for white or uncalibrated paints.",
    )
    tinting_peak_nm: float | None = None
    created_at: datetime
    updated_at: datetime


class PaintImportResult(_Out):
    created: list[str]
    updated: list[str]
    errors: list[str]


# --- settings -------------------------------------------------------------------------------


class SolverWeights(_Model):
    de: float = Field(1.0, ge=0)
    n_paints: float = Field(0.05, ge=0)
    cost: float = Field(0.5, ge=0)
    metamerism: float = Field(0.05, ge=0)


class AppSettings(_Model):
    currency: str = "SGD"
    dispenser_channels: int = Field(10, ge=1, le=64)
    batch_volume_ml: float = Field(100.0, gt=0)
    dispenser_resolution_ml: float = Field(0.05, gt=0)
    saunderson_k1: float = Field(0.0, ge=0, lt=1)
    saunderson_k2: float = Field(0.5, ge=0, lt=1)
    illuminant: Illuminant = Illuminant.D65
    max_paints: int = Field(5, ge=1, le=8)
    min_fraction: float = Field(0.02, ge=0, lt=0.5)
    top_n: int = Field(5, ge=1, le=20)
    weights: SolverWeights = Field(default_factory=SolverWeights)
    out_of_gamut_de: float = Field(1.0, gt=0)
    worksheet_batch_g: float = Field(10.0, gt=0)
    worksheet_scale_resolution_g: float = Field(0.01, gt=0)
    worksheet_gap_um: float = Field(150.0, gt=0)
    seed: int = 1234
    # Instrument self-test thresholds (guesses, not manufacturer figures; docs/ASSUMPTIONS.md)
    selftest_warn_de: float = Field(0.5, gt=0, description="WARN if max dE2000 vs mean exceeds")
    selftest_fail_de: float = Field(1.0, gt=0, description="FAIL if max dE2000 vs mean exceeds")
    selftest_white_min: float = Field(0.60, ge=0, le=1.2)
    selftest_white_max: float = Field(1.05, ge=0, le=1.2)
    selftest_max_band_jump: float = Field(0.05, gt=0)
    selftest_smoothness_rms: float = Field(0.01, gt=0)
    selftest_cast_chroma: float = Field(3.0, gt=0)

    @model_validator(mode="after")
    def _selftest_order(self) -> AppSettings:
        if self.selftest_warn_de > self.selftest_fail_de:
            raise ValueError("selftest_warn_de must be <= selftest_fail_de")
        if self.selftest_white_min >= self.selftest_white_max:
            raise ValueError("selftest_white_min must be < selftest_white_max")
        return self


class AppSettingsUpdate(_Model):
    currency: str | None = None
    dispenser_channels: int | None = Field(None, ge=1, le=64)
    batch_volume_ml: float | None = Field(None, gt=0)
    dispenser_resolution_ml: float | None = Field(None, gt=0)
    saunderson_k1: float | None = Field(None, ge=0, lt=1)
    saunderson_k2: float | None = Field(None, ge=0, lt=1)
    illuminant: Illuminant | None = None
    max_paints: int | None = Field(None, ge=1, le=8)
    min_fraction: float | None = Field(None, ge=0, lt=0.5)
    top_n: int | None = Field(None, ge=1, le=20)
    weights: SolverWeights | None = None
    out_of_gamut_de: float | None = Field(None, gt=0)
    worksheet_batch_g: float | None = Field(None, gt=0)
    worksheet_scale_resolution_g: float | None = Field(None, gt=0)
    worksheet_gap_um: float | None = Field(None, gt=0)
    seed: int | None = None
    selftest_warn_de: float | None = Field(None, gt=0)
    selftest_fail_de: float | None = Field(None, gt=0)
    selftest_white_min: float | None = Field(None, ge=0, le=1.2)
    selftest_white_max: float | None = Field(None, ge=0, le=1.2)
    selftest_max_band_jump: float | None = Field(None, gt=0)
    selftest_smoothness_rms: float | None = Field(None, gt=0)
    selftest_cast_chroma: float | None = Field(None, gt=0)


# --- colour library -------------------------------------------------------------------------


class ColorInput(_Model):
    """Exactly one of ``hex``, ``srgb`` (0-1), ``lab`` (D65) or ``spectrum`` (380-730 nm, 10 nm)."""

    hex: str | None = None
    srgb: list[float] | None = Field(None, min_length=3, max_length=3)
    lab: list[float] | None = Field(None, min_length=3, max_length=3)
    spectrum: Spectrum | None = Field(None, min_length=N_BANDS, max_length=N_BANDS)

    @model_validator(mode="after")
    def _one(self) -> ColorInput:
        given = [k for k in ("hex", "srgb", "lab", "spectrum") if getattr(self, k) is not None]
        if not given:
            raise ValueError("give one of hex, srgb, lab or spectrum")
        return self


class ColorCreate(ColorInput):
    name: str = Field(min_length=1, max_length=120)
    source: str = ""
    notes: str = ""


class ColorUpdate(_Model):
    name: str | None = Field(None, min_length=1, max_length=120)
    source: str | None = None
    notes: str | None = None
    hex: str | None = None
    lab: list[float] | None = Field(None, min_length=3, max_length=3)
    spectrum: Spectrum | None = Field(None, min_length=N_BANDS, max_length=N_BANDS)


class ColorRead(_Out):
    id: int
    name: str
    source: str
    hex: str
    srgb: list[float]
    lab: list[float]
    spectrum: Spectrum | None
    in_srgb_gamut: bool
    notes: str


class ColorImportResult(_Out):
    created: int
    updated: int
    errors: list[str]


# --- worksheet ------------------------------------------------------------------------------


class WorksheetOptionsIn(_Model):
    batch_g: float | None = Field(None, gt=0)
    scale_resolution_g: float | None = Field(None, gt=0)
    standard_gap_um: float | None = Field(None, gt=0)
    white_gaps_um: list[float] = Field(default_factory=lambda: [75.0, 150.0, 300.0])
    holdout_every: int = Field(3, ge=1)
    n_neutral_per_level: int = Field(2, ge=0, le=20)
    n_dark: int = Field(6, ge=0, le=50)
    n_random: int = Field(12, ge=0, le=200)
    max_paints: int = Field(5, ge=3, le=8)
    seed: int = 42
    spare_fraction: float = Field(0.2, ge=0, le=2)
    include_pairs: bool = True


class WorksheetRequest(_Model):
    paint_ids: list[str] | None = Field(None, description="Default: all active paints")
    options: WorksheetOptionsIn = Field(default_factory=WorksheetOptionsIn)
    title: str = "Calibration worksheet"


class WorksheetDrawdown(_Out):
    drawdown_id: str
    group: str
    type: str
    components: dict[str, float]
    masses_g: dict[str, float]
    masses_rounded_g: dict[str, float]
    gap_um: float
    holdout: bool
    low_mass: list[str]
    sample_ids: list[str]
    notes: str


class WorksheetRow(_Out):
    sample_id: str
    drawdown_id: str
    type: str
    substrate: str
    notes: str
    predicted_hex: str | None = Field(
        None, description="Expected colour on this background (active model), if available"
    )
    predicted_lab: list[float] | None = None


class LowMassOut(_Out):
    drawdown_id: str
    paint_id: str
    mass_g: float
    suggested_batch_g: float
    suggest_dilution: bool
    message: str


class WorksheetPaint(_Out):
    name: str
    role: str
    density_g_per_ml: float


class WorksheetResponse(_Out):
    preview_model_version: int | None = None
    preview_model_source: str | None = None
    options: dict[str, Any]
    warnings: list[str]
    n_drawdowns: int
    n_rows: int
    n_holdout: int
    drawdowns: list[WorksheetDrawdown]
    rows: list[WorksheetRow]
    totals_g: dict[str, float]
    low_mass: list[LowMassOut]
    paints: dict[str, WorksheetPaint]


# --- calibration ----------------------------------------------------------------------------


class ValidationIssueOut(_Out):
    row: int | None
    column: str | None
    code: str
    message: str
    severity: Literal["error", "warning"]


class ValidationReportOut(_Out):
    ok: bool
    n_rows: int
    n_valid: int
    n_errors: int
    n_warnings: int
    issues: list[ValidationIssueOut]
    wavelengths_in: list[float]


class CalibrationTextIn(_Model):
    csv: str
    filename: str = "upload.csv"


class UploadResult(_Out):
    report: ValidationReportOut
    upload_id: int | None
    stored: int
    replaced: int


class SampleRead(_Out):
    id: str
    type: str
    substrate: str
    components: dict[str, float]
    planned_components: dict[str, float] | None
    masses_g: dict[str, float] | None
    gap_um: float | None
    holdout: bool
    reflectance: Spectrum
    spread: Spectrum | None
    n_readings: int | None
    measured_at: str | None
    notes: str
    hex: str
    upload_id: int | None


class FitRequest(_Model):
    k1: float | None = Field(None, ge=0, lt=1)
    k2: float | None = Field(None, ge=0, lt=1)
    smoothness: float = Field(0.003, ge=0)
    k_folds: int = Field(5, ge=2, le=20)
    activate: bool = True
    notes: str = ""


class FitRunRead(_Out):
    id: int
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: float
    message: str
    error: str | None
    model_id: int | None
    model_version: int | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class HoldoutOut(_Out):
    method: str
    n_samples: int
    mean_de: float | None
    median_de: float | None
    p95_de: float | None
    max_de: float | None
    mean_rms: float | None
    noise_floor_mean_de: float | None


class ResidualOut(_Out):
    sample_id: str
    type: str
    substrate: str
    holdout: bool
    rms: float
    de2000: float
    outlier: bool
    noise_floor_de: float


ModelSource = Literal["calibration", "swatches"]


class ModelSummary(_Out):
    version: int
    active: bool
    source: ModelSource = Field(
        "calibration", description="calibration: fitted from measurements; swatches: uncalibrated"
    )
    created_at: datetime
    paint_ids: list[str]
    n_samples: int
    k1: float
    k2: float
    illuminant: str
    observer: str
    holdout: HoldoutOut
    warnings: list[str]
    notes: str


class ModelDetail(ModelSummary):
    diagnostics: dict[str, Any]
    residuals: list[ResidualOut]


class StrengthOut(_Out):
    reduction_fraction: float
    reduction_ks: float = Field(description="K/S of the reduction at its absorption peak")
    peak_nm: float
    reduction_lab: list[float]
    reduction_hex: str
    relative_pct: float | None = Field(
        None, description="Relative tinting strength vs reference_version (100 = equal)"
    )


class PaintSpectra(_Out):
    paint_id: str
    name: str
    K: Spectrum
    S: Spectrum
    ks: Spectrum
    masstone: Spectrum
    masstone_hex: str
    strength: StrengthOut | None = None


class ModelSpectra(_Out):
    version: int
    k1: float
    k2: float
    reference_version: int | None = None
    wavelengths: list[float]
    paints: list[PaintSpectra]
    tau: Spectrum
    substrate_white: Spectrum
    substrate_black: Spectrum


# --- mixing ---------------------------------------------------------------------------------


class TargetIn(_Model):
    """One of ``lab``, ``srgb`` (0-1), ``hex``, ``library_id`` or ``spectrum``."""

    lab: list[float] | None = Field(None, min_length=3, max_length=3)
    srgb: list[float] | None = Field(None, min_length=3, max_length=3)
    hex: str | None = None
    library_id: int | None = None
    spectrum: Spectrum | None = Field(None, min_length=N_BANDS, max_length=N_BANDS)
    name: str = ""

    @model_validator(mode="after")
    def _one(self) -> TargetIn:
        given = [
            k
            for k in ("lab", "srgb", "hex", "library_id", "spectrum")
            if getattr(self, k) is not None
        ]
        if len(given) != 1:
            raise ValueError("give exactly one of lab, srgb, hex, library_id or spectrum")
        return self


class SolveRequest(_Model):
    target: TargetIn
    pool: list[str] | None = Field(None, description="Paint ids; default = loaded paints")
    max_paints: int | None = Field(None, ge=1, le=8)
    min_fraction: float | None = Field(None, ge=0, lt=0.5)
    include_white: bool | None = Field(
        None, description="null: allowed, true: required in every recipe, false: excluded"
    )
    illuminant: Illuminant | None = None
    batch_volume_ml: float | None = Field(None, gt=0)
    resolution_ml: float | None = Field(None, gt=0)
    weights: SolverWeights | None = None
    top_n: int | None = Field(None, ge=1, le=20)
    seed: int | None = None
    search: Literal["auto", "exhaustive", "staged"] = "auto"


class ComponentOut(_Out):
    paint_id: str
    name: str
    fraction: float
    fraction_continuous: float
    volume_ml: float
    mass_g: float
    cost: float


class CandidateOut(_Out):
    rank: int
    components: list[ComponentOut]
    predicted_spectrum: Spectrum
    predicted_lab: list[float]
    predicted_hex: str
    de2000: float
    de2000_continuous: float
    cost: float
    cost_per_ml: float
    currency: str
    metamerism: dict[str, float]
    dose_sensitivity: float
    objective: float
    warnings: list[str]


class SolveResponse(_Out):
    target_name: str
    target_lab: list[float]
    target_hex: str
    target_in_srgb_gamut: bool
    reference_spectrum: Spectrum
    reference_spectrum_source: Literal["measured", "reconstructed"]
    candidates: list[CandidateOut]
    in_gamut: bool | None
    nearest_de: float
    warnings: list[str]
    search: str
    n_subsets: int
    duration_s: float
    model_version: int
    model_source: ModelSource = "calibration"
    pool: list[str]
    batch_volume_ml: float
    illuminant: str


class PredictRequest(_Model):
    components: dict[str, float] = Field(min_length=1)


class PredictResponse(_Out):
    wavelengths: list[float]
    spectrum: Spectrum
    lab: dict[str, list[float]]
    hex: str
    out_of_srgb_gamut: bool
    model_version: int
    model_source: ModelSource = "calibration"


class GamutSliceOut(_Out):
    L: float
    hue_deg: list[float]
    chroma: list[float]
    a: list[float]
    b: list[float]


class GamutResponse(_Out):
    pool: list[str]
    L_min: float
    L_max: float
    n_samples: int
    slices: list[GamutSliceOut]
    model_version: int


class RampRequest(_Model):
    paint_a: str
    paint_b: str | None = Field(None, description="Default: the active model's first white")
    steps: int = Field(9, ge=2, le=50)
    scale: Literal["linear", "log"] = Field(
        "linear", description="log: paint A diluted by the same factor each step (tint ladder)"
    )
    min_fraction: float = Field(0.01, gt=0, lt=1, description="Last fraction of A for log")


class RampStepOut(_Out):
    fraction_a: float
    lab: list[float]
    hex: str
    out_of_srgb_gamut: bool
    spectrum: Spectrum


class RampResponse(_Out):
    paint_a: str
    paint_b: str
    model_version: int
    model_source: str
    steps: list[RampStepOut]


class Health(_Out):
    status: str
    version: str
    active_model_version: int | None
    active_model_source: ModelSource | None = None


class SwatchModelRequest(_Model):
    paint_ids: list[str] | None = Field(
        None, description="Default: all active paints that have a swatch_hex"
    )
    activate: bool = True
    default_scattering: float = Field(
        0.3, gt=0, le=5, description="S relative to white for paints without a tint swatch"
    )
    notes: str = ""


class SwatchModelResult(_Out):
    model: ModelSummary
    scattering_source: dict[str, Literal["white", "tint", "assumed"]]
    tint_match_de: dict[str, float]
    warnings: list[str]


# --- jobs -----------------------------------------------------------------------------------


class JobCreate(_Model):
    name: str = ""
    target: TargetIn
    components: dict[str, float] = Field(
        min_length=1, description="Recipe volume fractions (e.g. a solve candidate)"
    )
    batch_volume_ml: float | None = Field(None, gt=0)
    constraints: dict[str, Any] = Field(
        default_factory=dict, description="Solve request, for reference"
    )


class DispenseRequest(_Model):
    simulate: bool = Field(True, description="Only the simulated dispenser exists so far")
    rel_sigma: float = Field(0.01, ge=0, le=0.5)
    abs_sigma_ml: float = Field(0.01, ge=0)
    seed: int | None = None


class MeasurementIn(_Model):
    """A measured spectrum or Lab of the mixed paint, or ``simulate`` to use the simulator."""

    spectrum: Spectrum | None = Field(None, min_length=N_BANDS, max_length=N_BANDS)
    lab: list[float] | None = Field(None, min_length=3, max_length=3)
    simulate: bool = False
    simulate_gain: float = Field(1.0, gt=0, description="Simulated model/instrument bias")
    simulate_offset: float = 0.0
    simulate_noise: float = Field(0.001, ge=0)
    seed: int | None = None

    @model_validator(mode="after")
    def _one(self) -> MeasurementIn:
        if not self.simulate and self.spectrum is None and self.lab is None:
            raise ValueError("give spectrum, lab or simulate=true")
        return self


class CorrectRequest(_Model):
    mode: Literal["additions", "remix"] = "additions"
    damping: float = Field(1e-3, ge=0)
    tolerance_de: float = Field(0.5, gt=0)
    max_iterations: int = Field(5, ge=1, le=20)


class JobRead(_Out):
    id: int
    name: str
    status: str
    target: dict[str, Any]
    constraints: dict[str, Any]
    recipe: dict[str, Any]
    batch_volume_ml: float
    model_version: int | None
    dispensed: dict[str, Any] | None
    measured: dict[str, Any] | None
    corrections: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
