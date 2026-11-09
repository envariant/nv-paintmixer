"""Measurement source protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import numpy as np

from paintmixer.calibration.format import Substrate
from paintmixer.colorsci.spectral import resample
from paintmixer.colorsci.types import FloatArray


@dataclass(frozen=True)
class MeasureRequest:
    """What is about to be measured. Simulators use the composition; instruments ignore it."""

    sample_id: str
    substrate: Substrate | None = None
    components: dict[str, float] = field(default_factory=dict)
    gap_um: float | None = None  # None = opaque film (dispensed mix, measured in the cup)


@dataclass(frozen=True)
class Reading:
    reflectance: FloatArray  # (N_BANDS,) on the canonical grid, 0-1
    wavelengths_in: tuple[float, ...] = ()
    raw: tuple[float, ...] = ()
    source: str = ""
    taken_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @classmethod
    def from_raw(
        cls, wavelengths: list[float], values: list[float], *, scale: float = 1.0, source: str = ""
    ) -> Reading:
        v = np.asarray(values, dtype=np.float64) * scale
        return cls(resample(wavelengths, v), tuple(wavelengths), tuple(values), source)


class MeasurementError(RuntimeError):
    pass


@runtime_checkable
class MeasurementSource(Protocol):
    name: str

    def open(self) -> None:
        """Connect / calibrate. May prompt the operator via the source's prompt callback."""

    def read(self, request: MeasureRequest) -> Reading:
        """Take one reading."""

    def close(self) -> None: ...
