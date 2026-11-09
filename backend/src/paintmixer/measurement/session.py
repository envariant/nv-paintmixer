"""Operator-guided measurement session (``paintmixer measure session``).

Walks the worksheet sample list, takes N readings per sample (one sample = one background of a
drawdown), stores the mean and per-band spread, warns when repeat readings disagree by more
than ``max_de`` dE2000, and appends each finished row to the calibration CSV immediately so an
interrupted session can be resumed (finished sample ids are skipped).
"""

from __future__ import annotations

import csv
import io
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from paintmixer.calibration.format import (
    BASE_COLUMNS,
    SPECTRUM_COLUMNS,
    SPREAD_COLUMNS,
    SampleType,
    Substrate,
)
from paintmixer.colorsci.convert import reflectance_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.spectral import N_BANDS
from paintmixer.colorsci.types import FloatArray
from paintmixer.measurement.base import MeasurementSource, MeasureRequest

OUT_COLUMNS = [
    *BASE_COLUMNS,
    "components_mass_g",
    "measured_at",
    "n_readings",
    *SPECTRUM_COLUMNS,
    *SPREAD_COLUMNS,
]


@dataclass
class SessionSample:
    sample_id: str
    type: str
    substrate: str
    components: str
    notes: str
    components_mass_g: str = ""

    @property
    def components_dict(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for tok in self.components.split(";"):
            if ":" in tok:
                k, v = tok.split(":")
                out[k.strip()] = float(v)
        return out

    @property
    def gap_um(self) -> float | None:
        for tok in self.notes.split(";"):
            if tok.strip().startswith("gap_um="):
                return float(tok.split("=")[1])
        return None

    @property
    def drawdown_id(self) -> str:
        return self.sample_id[:-2] if self.sample_id[-2:] in ("-W", "-B") else self.sample_id


def load_worksheet_csv(text: str) -> list[SessionSample]:
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    out = []
    for r in rows:
        if not r.get("sample_id") or r["sample_id"].startswith("#"):
            continue
        SampleType(r["type"])  # validate early
        out.append(
            SessionSample(
                r["sample_id"],
                r["type"],
                r["substrate"],
                r.get("components", "") or "",
                r.get("notes", "") or "",
                r.get("components_mass_g", "") or "",
            )
        )
    return out


def done_ids(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open() as fh:
        return {r["sample_id"] for r in csv.DictReader(fh) if r.get("sample_id")}


@dataclass
class SampleResult:
    sample_id: str
    mean: FloatArray
    spread: FloatArray
    max_de: float
    accepted_with_warning: bool = False


@dataclass
class SessionSummary:
    measured: list[SampleResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    already_done: int = 0
    warnings: list[str] = field(default_factory=list)
    quit_early: bool = False


def max_pairwise_de(readings: FloatArray) -> float:
    lab = reflectance_to_lab(readings)
    if len(lab) < 2:
        return 0.0
    pairs = list(itertools.combinations(range(len(lab)), 2))
    a = np.array([lab[i] for i, _ in pairs])
    b = np.array([lab[j] for _, j in pairs])
    return float(delta_e_2000(a, b).max())


class MeasureSession:
    def __init__(
        self,
        samples: list[SessionSample],
        source: MeasurementSource,
        out_path: Path,
        *,
        readings: int = 3,
        max_de: float = 0.5,
        ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print,
        ask_masses: bool = False,
    ) -> None:
        self.samples = samples
        self.source = source
        self.out_path = out_path
        self.readings = readings
        self.max_de = max_de
        self.ask = ask
        self.say = say
        self.ask_masses = ask_masses
        self._masses: dict[str, str] = {}

    def _write(self, s: SessionSample, mean: FloatArray, spread: FloatArray, at: str) -> None:
        new = not self.out_path.exists() or self.out_path.stat().st_size == 0
        with self.out_path.open("a", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            if new:
                w.writerow(OUT_COLUMNS)
            masses = self._masses.get(s.drawdown_id, s.components_mass_g)
            w.writerow(
                [
                    s.sample_id,
                    s.type,
                    s.substrate,
                    s.components,
                    s.notes,
                    masses,
                    at,
                    str(self.readings),
                ]
                + [f"{v:.5f}" for v in mean]
                + [f"{v:.5f}" for v in spread]
            )
            fh.flush()

    def _request(self, s: SessionSample) -> MeasureRequest:
        sub = Substrate(s.substrate) if s.substrate else None
        return MeasureRequest(s.sample_id, sub, s.components_dict, s.gap_um)

    def run(self) -> SessionSummary:
        summary = SessionSummary()
        done = done_ids(self.out_path)
        todo = [s for s in self.samples if s.sample_id not in done]
        summary.already_done = len(self.samples) - len(todo)
        if summary.already_done:
            self.say(
                f"Resuming: {summary.already_done} samples already measured, {len(todo)} to go."
            )
        self.source.open()
        try:
            for n, s in enumerate(todo, start=1):
                if (
                    self.ask_masses
                    and s.components_dict
                    and len(s.components_dict) > 1
                    and s.drawdown_id not in self._masses
                ):
                    m = self.ask(
                        f"Actual weighed masses for {s.drawdown_id} as paint:g;... "
                        f"(planned {s.components}; Enter to skip): "
                    ).strip()
                    self._masses[s.drawdown_id] = m
                cmd = (
                    self.ask(
                        f"[{n}/{len(todo)}] {s.sample_id} on {s.substrate or '-'} background: "
                        "Enter = measure, s = skip, q = quit: "
                    )
                    .strip()
                    .lower()
                )
                if cmd == "q":
                    summary.quit_early = True
                    break
                if cmd == "s":
                    summary.skipped.append(s.sample_id)
                    continue
                while True:
                    reads = np.stack(
                        [
                            self.source.read(self._request(s)).reflectance
                            for _ in range(self.readings)
                        ]
                    )
                    de = max_pairwise_de(reads)
                    if de <= self.max_de:
                        warned = False
                        break
                    msg = (
                        f"{s.sample_id}: repeat readings differ by {de:.2f} dE2000 "
                        f"(> {self.max_de:g}); check placement and surface."
                    )
                    self.say("WARNING " + msg)
                    again = self.ask("r = re-measure, a = accept anyway: ").strip().lower()
                    if again != "r":
                        summary.warnings.append(msg)
                        warned = True
                        break
                from datetime import UTC, datetime

                mean = reads.mean(axis=0)
                spread = reads.std(axis=0, ddof=1) if len(reads) > 1 else np.zeros(N_BANDS)
                self._write(s, mean, spread, datetime.now(UTC).isoformat(timespec="seconds"))
                summary.measured.append(SampleResult(s.sample_id, mean, spread, de, warned))
                self.say(f"  saved {s.sample_id} (max repeat dE2000 {de:.2f})")
        finally:
            self.source.close()
        return summary
