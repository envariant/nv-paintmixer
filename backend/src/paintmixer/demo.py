"""Seed a demo database: the five-paint CMYKW starter set, calibrated and ready to solve.

``seed_demo`` (CLI: ``paintmixer seed-demo``; or ``PAINTMIXER_SEED_DEMO=1`` to seed an empty
database on startup) loads the synthetic sample data from ``sample_data/``:

1. the starter paints White, Black, Cyan, Magenta and Yellow, loaded on channels 1-5;
2. the colour library;
3. the starter calibration drawdowns (124 measurements) and a fit of them -> the active model;
4. an uncalibrated swatch model of the same paints as a second, *inactive* version, so model
   versions (and their gamuts) can be compared.

It never deletes anything: paints, colours and samples are upserted, and models are only created
when the database has no model of that kind yet (``refit=True`` always adds new versions).
The data is synthetic (known K/S), not measurements of real products.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, col, select

from paintmixer.api.importers import (
    create_fit_run,
    import_colors_csv,
    import_paints_csv,
    run_fit,
    store_calibration,
    store_swatch_model,
    swatch_inputs,
)
from paintmixer.api.schemas import FitRequest
from paintmixer.api.services import load_settings
from paintmixer.calibration.swatch import model_from_swatches
from paintmixer.calibration.synthetic import STARTER_IDS
from paintmixer.db import models as m
from paintmixer.db.session import get_engine, migrate

DEMO_PAINTS = STARTER_IDS  # white, black, cyan, magenta, yellow
CALIBRATION_FILE = "calibration_starter5.csv"


def default_sample_dir() -> Path:
    """``sample_data/`` of the repository this package is installed from."""
    here = Path(__file__).resolve()
    for d in here.parents:
        if (d / "sample_data" / CALIBRATION_FILE).is_file():
            return d / "sample_data"
    return Path.cwd() / "sample_data"


@dataclass
class SeedReport:
    paints: list[str] = field(default_factory=list)
    colours_created: int = 0
    colours_updated: int = 0
    samples_stored: int = 0
    samples_replaced: int = 0
    calibrated_version: int | None = None
    swatch_version: int | None = None
    active_version: int | None = None
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"paints: {', '.join(self.paints)} (loaded on channels 1-{len(self.paints)})",
            f"colour library: {self.colours_created} created, {self.colours_updated} updated",
            f"calibration samples: {self.samples_stored} stored ({self.samples_replaced} replaced)",
            f"calibrated model: v{self.calibrated_version}"
            + (" (active)" if self.active_version == self.calibrated_version else ""),
            f"swatch model (uncalibrated, inactive): v{self.swatch_version}",
        ]
        lines += [f"skipped: {s}" for s in self.skipped]
        lines += [f"error: {e}" for e in self.errors]
        return "\n".join(lines)


def database_is_empty(database_url: str) -> bool:
    migrate(database_url)
    with Session(get_engine(database_url)) as s:
        return (
            s.exec(select(m.Paint)).first() is None
            and s.exec(select(m.FittedModel)).first() is None
        )


def _latest(s: Session, source: str) -> m.FittedModel | None:
    return s.exec(
        select(m.FittedModel)
        .where(m.FittedModel.source == source)
        .order_by(col(m.FittedModel.version).desc())
    ).first()


def seed_demo(
    database_url: str, sample_dir: Path | None = None, *, refit: bool = False
) -> SeedReport:
    root = sample_dir or default_sample_dir()
    files = {n: root / n for n in ("paints.csv", "color_library.csv", CALIBRATION_FILE)}
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"sample data not found: {', '.join(missing)}")
    migrate(database_url)
    engine = get_engine(database_url)
    rep = SeedReport()
    with Session(engine) as s:
        res = import_paints_csv(s, files["paints.csv"].read_text(), only=DEMO_PAINTS)
        rep.errors += res.errors
        rep.paints = [p for p in DEMO_PAINTS if s.get(m.Paint, p) is not None]
        col_res = import_colors_csv(s, files["color_library.csv"].read_text())
        rep.colours_created, rep.colours_updated = col_res.created, col_res.updated
        rep.errors += col_res.errors
        up = store_calibration(s, files[CALIBRATION_FILE].read_text(), CALIBRATION_FILE)
        rep.samples_stored, rep.samples_replaced = up.stored, up.replaced
        if not up.report.ok:
            rep.errors.append("calibration file did not validate; samples not stored")

        calibrated = _latest(s, "calibration")
        if calibrated is None or refit:
            run = create_fit_run(
                s, FitRequest(activate=True, notes="demo: CMYKW starter set (synthetic)")
            )
            assert run.id is not None
            run_fit(database_url, run.id)  # inline: about a second
            s.expire_all()
            finished = s.get(m.FitRun, run.id)
            if finished is None or finished.status != "succeeded":
                raise RuntimeError(f"demo fit failed: {finished.error if finished else '?'}")
            calibrated = _latest(s, "calibration")
        else:
            rep.skipped.append(f"fit (calibrated model v{calibrated.version} already exists)")
        assert calibrated is not None
        rep.calibrated_version = calibrated.version

        swatch = _latest(s, "swatches")
        if swatch is None or refit:
            settings = load_settings(s)
            sm = model_from_swatches(
                swatch_inputs(s, list(DEMO_PAINTS)),
                k1=settings.saunderson_k1,
                k2=settings.saunderson_k2,
            )
            swatch = store_swatch_model(
                s, sm, activate=False, notes="demo: CMYKW from swatch colours (uncalibrated)"
            )
        else:
            rep.skipped.append(f"swatch model (v{swatch.version} already exists)")
        rep.swatch_version = swatch.version
        active = s.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
        rep.active_version = active.version if active else None
    return rep
