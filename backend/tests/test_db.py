from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlmodel import Session, SQLModel, select

import paintmixer.db.models as m
from paintmixer.db.session import get_engine, migrate


def test_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    migrate(url)
    engine = get_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
    assert diff == [], f"models and migrations differ; generate a new revision: {diff}"
    with Session(engine) as s:
        s.add(m.Paint(id="titanium-white", name="Titanium White", role="white"))
        s.add(
            m.FittedModel(version=1, K=[[0.1] * 31], S=[[1.0] * 31], paint_ids=["titanium-white"])
        )
        s.commit()
        fm = s.exec(select(m.FittedModel)).one()
        assert fm.K[0][0] == 0.1


def test_grid_migration_pads_31_band_data(tmp_path: Path) -> None:
    """0002 extends stored 400-700 nm spectra to 380-730 nm by holding the edge values."""
    from alembic import command

    from paintmixer.db.session import alembic_config

    url = f"sqlite:///{tmp_path / 'old.db'}"
    get_engine(url)
    command.upgrade(alembic_config(url), "0001")
    old = [0.1 + i / 100 for i in range(31)]
    with Session(get_engine(url)) as s:
        s.add(
            m.CalibrationSample(
                id="S1", type="mixture", substrate="white", reflectance=old, spread=None
            )
        )
        s.add(
            m.FittedModel(
                version=1, K=[old, old], S=[[1.0] * 31, old], tau=old, paint_ids=["a", "b"]
            )
        )
        s.add(m.ColorLibraryEntry(name="x", spectrum=old, lab=[50, 0, 0], srgb=[0.5] * 3))
        s.add(
            m.Job(
                target={"lab": [1, 2, 3], "spectrum": old},
                measured={"spectrum": old, "lab": [1, 2, 3]},
            )
        )
        s.commit()
    command.upgrade(alembic_config(url), "head")
    with Session(get_engine(url)) as s:
        smp = s.get(m.CalibrationSample, "S1")
        assert smp is not None and len(smp.reflectance) == 36
        assert smp.reflectance[:3] == [old[0]] * 3 and smp.reflectance[-4:] == [old[-1]] * 4
        assert smp.reflectance[2:33] == old and smp.spread is None
        fm = s.exec(select(m.FittedModel)).one()
        assert [len(r) for r in fm.K + fm.S] == [36] * 4 and len(fm.tau) == 36
        assert fm.substrate_white == []  # empty lists are left alone
        job = s.exec(select(m.Job)).one()
        assert len(job.target["spectrum"]) == 36 and job.target["lab"] == [1, 2, 3]
        assert len(job.measured["spectrum"]) == 36  # type: ignore[index]
    command.downgrade(alembic_config(url), "0001")
    with Session(get_engine(url)) as s:
        assert s.get(m.CalibrationSample, "S1").reflectance == old  # type: ignore[union-attr]
