from __future__ import annotations

from pathlib import Path

from paintmixer.domain import PaintInfo, PaintRole

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA = ROOT / "sample_data"


def load_paints_csv(path: Path = SAMPLE_DATA / "paints.csv") -> dict[str, PaintInfo]:
    import csv

    with path.open() as fh:
        return {
            r["id"]: PaintInfo(
                r["id"],
                PaintRole(r["role"]),
                float(r["density_g_per_ml"]),
                name=r["name"],
                cost_per_ml=float(r["cost_per_ml"]),
                min_dose_ml=float(r["min_dose_ml"]),
            )
            for r in csv.DictReader(fh)
        }
