"""Plain domain types shared by the pure libraries (no DB or web imports)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PaintRole(StrEnum):
    WHITE = "white"
    BLACK = "black"
    CHROMATIC = "chromatic"


@dataclass(frozen=True)
class PaintInfo:
    """What the calibration and planning code needs to know about a paint."""

    id: str
    role: PaintRole
    density_g_per_ml: float = 1.0
    name: str = ""
    cost_per_ml: float = 0.0
    min_dose_ml: float = 0.0

    @property
    def label(self) -> str:
        return self.name or self.id
