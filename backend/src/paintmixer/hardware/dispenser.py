"""Dispenser abstraction and a simulator with dosing error."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class DispenseResult:
    paint_id: str
    channel: int
    requested_ml: float
    actual_ml: float


class DispenserError(RuntimeError):
    pass


@runtime_checkable
class Dispenser(Protocol):
    name: str

    def dispense(self, channel: int, volume_ml: float) -> float:
        """Dispense ``volume_ml`` from ``channel``; return the volume actually delivered."""


@dataclass
class SimulatedDispenser:
    """Dosing error = per-channel systematic bias + relative noise + absolute noise, quantised to
    the pump resolution."""

    resolution_ml: float = 0.05
    rel_sigma: float = 0.01
    abs_sigma_ml: float = 0.01
    bias: Mapping[int, float] = field(default_factory=dict)  # channel -> relative bias
    seed: int = 0
    name: str = "simulated"
    log: list[tuple[int, float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)

    def dispense(self, channel: int, volume_ml: float) -> float:
        if volume_ml < 0:
            raise DispenserError("volume must be >= 0")
        if volume_ml == 0:
            return 0.0
        v = volume_ml * (1.0 + self.bias.get(channel, 0.0))
        v *= 1.0 + self._rng.normal(0.0, self.rel_sigma)
        v += self._rng.normal(0.0, self.abs_sigma_ml)
        v = max(0.0, round(v / self.resolution_ml) * self.resolution_ml)
        self.log.append((channel, volume_ml, v))
        return float(v)


def dispense_recipe(
    dispenser: Dispenser, volumes_ml: Mapping[str, float], channels: Mapping[str, int]
) -> list[DispenseResult]:
    missing = [p for p in volumes_ml if p not in channels]
    if missing:
        raise DispenserError(f"paints not loaded on a dispenser channel: {', '.join(missing)}")
    return [
        DispenseResult(p, channels[p], float(v), dispenser.dispense(channels[p], float(v)))
        for p, v in volumes_ml.items()
        if v > 0
    ]
