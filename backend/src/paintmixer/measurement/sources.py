"""File import, simulated and camera measurement sources."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from paintmixer.calibration.format import Substrate
from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.types import FloatArray
from paintmixer.measurement.base import MeasurementError, MeasureRequest, Reading


class FileImportSource:
    """Replay spectra from a CSV with ``sample_id`` and ``r<nm>`` columns (any grid covering
    400-700 nm, values 0-1 or percent). Several rows with the same id are successive readings."""

    name = "file"

    def __init__(self, path: Path | str | None = None, text: str | None = None) -> None:
        content = text if text is not None else Path(path or "").read_text()
        reader = csv.DictReader(io.StringIO(content))
        cols = [c for c in (reader.fieldnames or []) if c and c[0] == "r" and c[1:].isdigit()]
        if not cols:
            raise MeasurementError("no r<nm> spectral columns in file")
        self._wl = [float(c[1:]) for c in cols]
        self._rows: dict[str, list[list[float]]] = defaultdict(list)
        for r in reader:
            self._rows[r["sample_id"]].append([float(r[c]) for c in cols])
        self._next: dict[str, int] = defaultdict(int)

    def open(self) -> None:
        pass

    def read(self, request: MeasureRequest) -> Reading:
        rows = self._rows.get(request.sample_id)
        if not rows:
            raise MeasurementError(f"no spectrum for {request.sample_id!r} in file")
        i = self._next[request.sample_id] % len(rows)
        self._next[request.sample_id] += 1
        vals = rows[i]
        scale = 0.01 if max(vals) > 1.5 else 1.0
        return Reading.from_raw(self._wl, vals, scale=scale, source=self.name)

    def close(self) -> None:
        pass


class SimulatedSource:
    """Model-based instrument: K-M prediction + Gaussian noise + systematic bias.

    The bias models a model/instrument mismatch: ``R_meas = gain * R + offset`` per band (gain
    and offset may be arrays), applied before noise. ``fixed`` maps sample ids to known
    spectra (e.g. a white tile or grey references) that are returned instead of a K-M
    prediction. ``drift_per_read`` adds an instrument drift: reading ``k`` (0-based) is scaled by
    ``1 + drift_per_read * k``.
    """

    name = "simulated"

    def __init__(
        self,
        model: KMModel,
        paint_ids: Sequence[str],
        *,
        tau: FloatArray | None = None,
        substrate_white: FloatArray | None = None,
        substrate_black: FloatArray | None = None,
        noise: float = 0.002,
        gain: FloatArray | float = 1.0,
        offset: FloatArray | float = 0.0,
        seed: int = 0,
        fixed: Mapping[str, FloatArray] | None = None,
        drift_per_read: float = 0.0,
    ) -> None:
        from paintmixer.calibration.synthetic import substrate_black as sb
        from paintmixer.calibration.synthetic import substrate_white as sw
        from paintmixer.calibration.synthetic import true_tau

        self.model = model
        self.paint_ids = list(paint_ids)
        self.tau = tau if tau is not None else true_tau()
        self.sub_w = substrate_white if substrate_white is not None else sw()
        self.sub_b = substrate_black if substrate_black is not None else sb()
        self.noise = noise
        self.gain = gain
        self.offset = offset
        self.rng = np.random.default_rng(seed)
        self.fixed = {k: np.asarray(v, dtype=np.float64) for k, v in (fixed or {}).items()}
        self.drift_per_read = drift_per_read
        self.n_reads = 0

    def open(self) -> None:
        pass

    def clean(self, request: MeasureRequest) -> FloatArray:
        if request.sample_id in self.fixed:
            r = self.fixed[request.sample_id]
            return np.asarray(np.asarray(self.gain) * r + self.offset, dtype=np.float64)
        if not request.components:
            return self.sub_b if request.substrate == Substrate.BLACK else self.sub_w
        c = np.zeros(self.model.n_paints)
        for pid, f in request.components.items():
            if pid not in self.paint_ids:
                raise MeasurementError(f"simulator has no paint {pid!r}")
            c[self.paint_ids.index(pid)] = f
        c /= c.sum()
        if request.gap_um is None:
            r = self.model.reflectance(c)
        else:
            sub = self.sub_b if request.substrate == Substrate.BLACK else self.sub_w
            r = self.model.reflectance_layer(c, self.tau * request.gap_um, sub)
        return np.asarray(np.clip(np.asarray(self.gain) * r + self.offset, 0.0, 1.2))

    def read(self, request: MeasureRequest) -> Reading:
        drift = 1.0 + self.drift_per_read * self.n_reads
        self.n_reads += 1
        r = self.clean(request) * drift + self.rng.normal(0.0, self.noise, size=31)
        return Reading(np.clip(r, 0.0, 1.2), source=self.name)

    def close(self) -> None:
        pass


class CameraSource:
    """Placeholder for a calibrated-camera measurement source (not implemented yet)."""

    name = "camera"

    def open(self) -> None:
        raise NotImplementedError("CameraSource is a stub; use spotread, file or simulated")

    def read(self, request: MeasureRequest) -> Reading:
        raise NotImplementedError("CameraSource is a stub")

    def close(self) -> None:
        pass
