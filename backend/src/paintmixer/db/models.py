"""SQLModel tables. JSON columns hold arrays (spectra, K/S) and nested documents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Paint(SQLModel, table=True):
    id: str = Field(primary_key=True, max_length=64)  # slug
    name: str
    brand: str = ""
    pigment_code: str = ""
    role: str = Field(default="chromatic", index=True)  # white | black | chromatic
    density_g_per_ml: float = 1.0
    cost_per_ml: float = 0.0
    min_dose_ml: float = 0.0
    dispenser_channel: int | None = Field(default=None)
    loaded: bool = Field(default=False, index=True)
    parent_paint_id: str | None = Field(default=None, foreign_key="paint.id")
    dilution: float | None = None  # fraction of parent paint in a diluted stock
    active: bool = True
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CalibrationUpload(SQLModel, table=True):
    __tablename__ = "calibration_upload"
    id: int | None = Field(default=None, primary_key=True)
    filename: str = ""
    uploaded_at: datetime = Field(default_factory=utcnow)
    n_samples: int = 0
    issues: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))


class CalibrationSample(SQLModel, table=True):
    __tablename__ = "calibration_sample"
    id: str = Field(primary_key=True, max_length=128)  # sample_id from the CSV
    type: str = Field(index=True)
    substrate: str
    components: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    planned_components: dict[str, float] | None = Field(default=None, sa_column=Column(JSON))
    masses_g: dict[str, float] | None = Field(default=None, sa_column=Column(JSON))
    gap_um: float | None = None
    holdout: bool = False
    reflectance: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    spread: list[float] | None = Field(default=None, sa_column=Column(JSON))
    n_readings: int | None = None
    measured_at: str | None = None
    notes: str = ""
    upload_id: int | None = Field(default=None, foreign_key="calibration_upload.id")
    created_at: datetime = Field(default_factory=utcnow)


class ColorLibraryEntry(SQLModel, table=True):
    __tablename__ = "color_library_entry"
    __table_args__ = (UniqueConstraint("source", "name"),)
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    source: str = ""
    hex: str = ""
    srgb: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    lab: list[float] = Field(default_factory=list, sa_column=Column(JSON))  # D65
    spectrum: list[float] | None = Field(default=None, sa_column=Column(JSON))
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class FitRun(SQLModel, table=True):
    __tablename__ = "fit_run"
    id: int | None = Field(default=None, primary_key=True)
    status: str = "queued"  # queued | running | succeeded | failed
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    options: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    model_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class FittedModel(SQLModel, table=True):
    __tablename__ = "fitted_model"
    id: int | None = Field(default=None, primary_key=True)
    version: int = Field(index=True, unique=True)
    active: bool = Field(default=False, index=True)
    paint_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    K: list[list[float]] = Field(default_factory=list, sa_column=Column(JSON))
    S: list[list[float]] = Field(default_factory=list, sa_column=Column(JSON))
    tau: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    k1: float = 0.0
    k2: float = 0.5
    illuminant: str = "D65"
    observer: str = "CIE 1931 2"
    substrate_white: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    substrate_black: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    diagnostics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    holdout_report: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    n_samples: int = 0
    fit_run_id: int | None = Field(default=None, foreign_key="fit_run.id")
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    status: str = Field(default="draft", index=True)
    target: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    constraints: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    candidates: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    recipe: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    batch_volume_ml: float = 100.0
    model_version: int | None = None
    dispensed: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    measured: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    corrections: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CorrectionLog(SQLModel, table=True):
    """Residuals of measured mixes vs predictions: training data for a learned correction."""

    __tablename__ = "correction_log"
    id: int | None = Field(default=None, primary_key=True)
    job_id: int | None = Field(default=None, foreign_key="job.id", index=True)
    iteration: int = 0
    model_version: int | None = None
    fractions: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    predicted_lab: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    measured_lab: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    measured_spectrum: list[float] | None = Field(default=None, sa_column=Column(JSON))
    target_lab: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=64)
    value: Any = Field(default=None, sa_column=Column(JSON))
