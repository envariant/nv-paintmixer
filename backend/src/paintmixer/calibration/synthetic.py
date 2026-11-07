"""Synthetic paints and calibration data with known K/S, for development without hardware.

The generator plans a worksheet (:mod:`paintmixer.worksheet.plan`), simulates weighing errors,
renders every drawdown with the finite-thickness K-M model over measured-like substrates, adds
reflectance noise and returns rows in the calibration CSV format. The ground truth is returned
alongside so tests can check recovery.

Noise model: each row is the mean of three readings with per-reading sigma ``noise * sqrt(3)``,
so the reported reflectance has sigma ``noise`` (default 0.002) and ``spread`` is the per-band
standard deviation of the three readings.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from paintmixer.calibration.format import (
    CalibrationSampleData,
    SampleType,
    Substrate,
)
from paintmixer.colorsci.km import DEFAULT_K1, DEFAULT_K2, KMModel
from paintmixer.colorsci.spectral import WAVELENGTHS
from paintmixer.colorsci.types import FloatArray
from paintmixer.domain import PaintInfo, PaintRole
from paintmixer.worksheet.plan import WorksheetOptions, WorksheetPlan, plan_worksheet

WL = WAVELENGTHS


def _g(center: float, width: float) -> FloatArray:
    return np.asarray(np.exp(-0.5 * ((WL - center) / width) ** 2), dtype=np.float64)


def _sig(edge: float, width: float) -> FloatArray:
    """Smooth step that is ~1 below ``edge`` and ~0 above it."""
    return np.asarray(1.0 / (1.0 + np.exp((WL - edge) / width)), dtype=np.float64)


@dataclass(frozen=True)
class SyntheticPaint:
    info: PaintInfo
    K: FloatArray
    S: FloatArray


def _paint(
    pid: str,
    name: str,
    role: PaintRole,
    k: FloatArray,
    s: FloatArray | float,
    density: float,
    cost: float,
    pigment: str,
) -> tuple[SyntheticPaint, str]:
    s_arr = np.broadcast_to(np.asarray(s, dtype=np.float64), WL.shape).copy()
    info = PaintInfo(
        id=pid, role=role, density_g_per_ml=density, name=name, cost_per_ml=cost, min_dose_ml=0.05
    )
    return SyntheticPaint(info, np.asarray(k, dtype=np.float64), s_arr), pigment


def _catalogue() -> list[tuple[SyntheticPaint, str]]:
    lam = (WL - 550.0) / 150.0
    return [
        _paint(
            "titanium-white",
            "Titanium White",
            PaintRole.WHITE,
            0.003 + 0.004 * _g(400, 30) + 0.25 * _sig(405, 6),
            1.0,
            1.40,
            0.060,
            "PW6",
        ),
        _paint(
            "carbon-black",
            "Carbon Black",
            PaintRole.BLACK,
            10.0 * (1.0 - 0.06 * lam),
            0.30,
            1.15,
            0.080,
            "PBk7",
        ),
        _paint(
            "phthalo-blue",
            "Phthalo Blue (cyan)",
            PaintRole.CHROMATIC,
            0.05 + 16.0 * _g(625, 45) + 7.0 * _g(690, 35) + 0.6 * _sig(420, 10),
            0.12 + 0.04 * _g(450, 60),
            1.10,
            0.095,
            "PB15:3",
        ),
        _paint(
            "quinacridone-magenta",
            "Quinacridone Magenta",
            PaintRole.CHROMATIC,
            0.08 + 13.0 * _g(545, 38) + 2.0 * _g(420, 30),
            0.15 + 0.03 * _g(650, 80),
            1.10,
            0.120,
            "PR122",
        ),
        _paint(
            "arylide-yellow",
            "Arylide Yellow",
            PaintRole.CHROMATIC,
            0.03 + 15.0 * _sig(482, 11),
            0.35 + 0.05 * _g(600, 80),
            1.20,
            0.085,
            "PY74",
        ),
        _paint(
            "pyrrole-red",
            "Pyrrole Red (warm)",
            PaintRole.CHROMATIC,
            0.04 + 19.0 * _sig(578, 10),
            0.40,
            1.25,
            0.150,
            "PR254",
        ),
        _paint(
            "pyrrole-orange",
            "Pyrrole Orange",
            PaintRole.CHROMATIC,
            0.03 + 17.0 * _sig(545, 11),
            0.38,
            1.25,
            0.140,
            "PO73",
        ),
        _paint(
            "phthalo-green",
            "Phthalo Green",
            PaintRole.CHROMATIC,
            0.05 + 13.0 * _g(650, 55) + 9.0 * _sig(455, 14),
            0.12,
            1.10,
            0.095,
            "PG7",
        ),
        _paint(
            "dioxazine-violet",
            "Dioxazine Violet",
            PaintRole.CHROMATIC,
            0.10 + 18.0 * _g(575, 50) + 3.0 * _g(470, 30),
            0.10,
            1.10,
            0.160,
            "PV23",
        ),
    ]


STARTER_IDS = (
    "titanium-white",
    "carbon-black",
    "phthalo-blue",
    "quinacridone-magenta",
    "arylide-yellow",
)
POOL_IDS = (*STARTER_IDS, "pyrrole-red", "pyrrole-orange", "phthalo-green", "dioxazine-violet")


def synthetic_paints(ids: Sequence[str] = STARTER_IDS) -> list[SyntheticPaint]:
    cat = {p.info.id: p for p, _ in _catalogue()}
    return [cat[i] for i in ids]


def pigment_codes() -> dict[str, str]:
    return {p.info.id: code for p, code in _catalogue()}


def random_paints(n: int, seed: int = 0) -> list[SyntheticPaint]:
    """Random but plausible chromatic paints (one or two absorption bands)."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        k = 0.03 + rng.uniform(0.0, 0.1) * np.ones_like(WL)
        for _ in range(int(rng.integers(1, 3))):
            if rng.random() < 0.35:
                k = k + rng.uniform(8, 20) * _sig(rng.uniform(450, 600), rng.uniform(8, 16))
            else:
                k = k + rng.uniform(6, 18) * _g(rng.uniform(420, 690), rng.uniform(25, 60))
        s = rng.uniform(0.08, 0.45) * (1.0 + 0.1 * _g(rng.uniform(450, 650), 80))
        info = PaintInfo(
            id=f"synthetic-{i + 1:02d}",
            role=PaintRole.CHROMATIC,
            density_g_per_ml=1.15,
            name=f"Synthetic {i + 1}",
            cost_per_ml=float(rng.uniform(0.05, 0.2)),
            min_dose_ml=0.05,
        )
        out.append(SyntheticPaint(info, np.asarray(k, dtype=np.float64), np.asarray(s)))
    return out


def true_tau() -> FloatArray:
    """Optical thickness per micrometre of wet gap (white scattering per um), per band."""
    return np.asarray(0.06 * (550.0 / WL) ** 1.2, dtype=np.float64)


def substrate_white() -> FloatArray:
    return np.asarray(0.86 - 0.05 * _sig(420, 12) + 0.01 * (WL - 550) / 150, dtype=np.float64)


def substrate_black() -> FloatArray:
    return np.asarray(0.030 + 0.004 * (WL - 550) / 150, dtype=np.float64)


@dataclass
class SyntheticTruth:
    paints: list[SyntheticPaint]
    tau: FloatArray
    k1: float
    k2: float

    @property
    def model(self) -> KMModel:
        return KMModel(
            K=np.stack([p.K for p in self.paints]),
            S=np.stack([p.S for p in self.paints]),
            k1=self.k1,
            k2=self.k2,
        )

    @property
    def ids(self) -> list[str]:
        return [p.info.id for p in self.paints]

    def to_json(self) -> str:
        return json.dumps(
            {
                "wavelengths": WL.tolist(),
                "paint_ids": self.ids,
                "K": [p.K.round(6).tolist() for p in self.paints],
                "S": [p.S.round(6).tolist() for p in self.paints],
                "tau_per_um": self.tau.round(8).tolist(),
                "k1": self.k1,
                "k2": self.k2,
            },
            indent=1,
        )


def render(
    truth: SyntheticTruth,
    components: dict[str, float],
    substrate: Substrate,
    gap_um: float,
    sub_w: FloatArray | None = None,
    sub_b: FloatArray | None = None,
) -> FloatArray:
    model = truth.model
    c = np.zeros(model.n_paints)
    for pid, f in components.items():
        c[truth.ids.index(pid)] = f
    sub = (
        (sub_w if sub_w is not None else substrate_white())
        if substrate == Substrate.WHITE
        else (sub_b if sub_b is not None else substrate_black())
    )
    return model.reflectance_layer(c, truth.tau * gap_um, sub)


def generate_calibration(
    paints: Sequence[SyntheticPaint],
    *,
    options: WorksheetOptions | None = None,
    noise: float = 0.002,
    seed: int = 7,
    weigh: bool = True,
    k1: float = DEFAULT_K1,
    k2: float = DEFAULT_K2,
) -> tuple[list[CalibrationSampleData], SyntheticTruth, WorksheetPlan]:
    rng = np.random.default_rng(seed)
    truth = SyntheticTruth(list(paints), true_tau(), k1, k2)
    infos = {p.info.id: p.info for p in paints}
    plan = plan_worksheet([p.info for p in paints], options)
    res = plan.options.scale_resolution_g
    samples: list[CalibrationSampleData] = []
    for d in plan.drawdowns:
        actual = dict(d.components)
        masses: dict[str, float] | None = None
        if weigh and d.masses_g and len(d.components) > 1:
            masses = {}
            for pid, m in d.masses_g.items():
                weighed = m + rng.normal(0.0, 1.5 * res)
                masses[pid] = max(res, round(round(weighed / res) * res, 6))
            vols = {p: m / infos[p].density_g_per_ml for p, m in masses.items()}
            vt = sum(vols.values())
            actual = {p: v / vt for p, v in vols.items()}
        for sid, sub, stype in d.sample_ids():
            if stype == SampleType.SUBSTRATE_WHITE:
                clean = substrate_white()
            elif stype == SampleType.SUBSTRATE_BLACK:
                clean = substrate_black()
            else:
                clean = render(truth, actual, sub, d.gap_um)
            readings = clean + rng.normal(0.0, noise * np.sqrt(3.0), size=(3, clean.size))
            refl = np.clip(readings.mean(axis=0), 0.0, 1.2)
            spread = readings.std(axis=0, ddof=1)
            samples.append(
                CalibrationSampleData(
                    sample_id=sid,
                    type=stype,
                    substrate=sub,
                    components=actual
                    if stype not in (SampleType.SUBSTRATE_WHITE, SampleType.SUBSTRATE_BLACK)
                    else {},
                    reflectance=refl,
                    gap_um=d.gap_um if d.components else None,
                    holdout=d.holdout,
                    spread=spread,
                    planned_components=dict(d.components) if masses else None,
                    masses_g=masses,
                    n_readings=3,
                    notes=d.notes,
                )
            )
    return samples, truth, plan


def paints_csv(paints: Sequence[SyntheticPaint], loaded: Sequence[str] = STARTER_IDS) -> str:
    codes = pigment_codes()
    lines = [
        "id,name,brand,pigment_code,role,density_g_per_ml,cost_per_ml,min_dose_ml,"
        "dispenser_channel,loaded"
    ]
    channel = 0
    for p in paints:
        is_loaded = p.info.id in loaded
        if is_loaded:
            channel += 1
        lines.append(
            ",".join(
                [
                    p.info.id,
                    p.info.name,
                    "Synthetic",
                    codes.get(p.info.id, ""),
                    p.info.role.value,
                    f"{p.info.density_g_per_ml:g}",
                    f"{p.info.cost_per_ml:g}",
                    f"{p.info.min_dose_ml:g}",
                    str(channel) if is_loaded else "",
                    "true" if is_loaded else "false",
                ]
            )
        )
    return "\n".join(lines) + "\n"


def write_sample_data(out_dir: Path) -> list[Path]:
    """Regenerate the committed files in ``sample_data/``."""
    from paintmixer.calibration.format import write_calibration_csv

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    pool = synthetic_paints(POOL_IDS)
    p = out_dir / "paints.csv"
    p.write_text(paints_csv(pool))
    written.append(p)
    for name, ids in (("starter5", STARTER_IDS), ("pool9", POOL_IDS)):
        samples, truth, _ = generate_calibration(synthetic_paints(ids))
        p = out_dir / f"calibration_{name}.csv"
        p.write_text(write_calibration_csv(samples, include_masses=True, include_spread=True))
        written.append(p)
        p = out_dir / f"synthetic_truth_{name}.json"
        p.write_text(truth.to_json() + "\n")
        written.append(p)
    return written
