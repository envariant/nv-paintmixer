from __future__ import annotations

import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
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
        line = m.ModelLine(slug="default", name="Default")
        s.add(line)
        s.flush()
        assert line.id is not None
        s.add(
            m.FittedModel(
                version=1,
                line_id=line.id,
                K=[[0.1] * 31],
                S=[[1.0] * 31],
                paint_ids=["titanium-white"],
            )
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
    j = json.dumps
    now = "2026-01-01 00:00:00"
    # raw rows matching the 0001 schema (the ORM classes describe the latest schema)
    with get_engine(url).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO calibration_sample (id, type, substrate, holdout, notes, created_at,"
                " reflectance, spread, components) VALUES ('S1', 'mixture', 'white', 0, '', :t,"
                " :r, NULL, '{}')"
            ),
            {"t": now, "r": j(old)},
        )
        conn.execute(
            text(
                "INSERT INTO fitted_model (version, active, k1, k2, illuminant, observer,"
                " n_samples, notes, created_at, paint_ids, K, S, tau, substrate_white,"
                " substrate_black, diagnostics, holdout_report) VALUES (1, 1, 0, 0.5, 'D65',"
                " 'CIE 1931 2', 0, '', :t, :ids, :K, :S, :tau, '[]', '[]', '{}', '{}')"
            ),
            {
                "t": now,
                "ids": j(["a", "b"]),
                "K": j([old, old]),
                "S": j([[1.0] * 31, old]),
                "tau": j(old),
            },
        )
        conn.execute(
            text(
                "INSERT INTO job (name, status, batch_volume_ml, created_at, updated_at, target,"
                " measured, constraints, candidates, recipe, corrections) VALUES ('', 'draft',"
                " 100, :t, :t, :target, :measured, '{}', '[]', '{}', '[]')"
            ),
            {
                "t": now,
                "target": j({"lab": [1, 2, 3], "spectrum": old}),
                "measured": j({"spectrum": old, "lab": [1, 2, 3]}),
            },
        )
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


def test_model_line_migration_assigns_default_line(tmp_path: Path) -> None:
    """0004 puts existing models in a line "default", revisions in version order."""
    from alembic import command

    from paintmixer.db.session import alembic_config

    url = f"sqlite:///{tmp_path / 'lines.db'}"
    get_engine(url)
    command.upgrade(alembic_config(url), "0003")
    with get_engine(url).begin() as conn:
        for version, active in ((3, 0), (5, 1)):
            conn.execute(
                text(
                    "INSERT INTO fitted_model (version, active, source, k1, k2, illuminant,"
                    " observer, n_samples, notes, created_at, paint_ids, K, S, tau,"
                    " substrate_white, substrate_black, diagnostics, holdout_report) VALUES"
                    " (:v, :a, 'calibration', 0, 0.5, 'D65', 'CIE 1931 2', 0, '',"
                    " '2026-01-01 00:00:00', '[]', '[]', '[]', '[]', '[]', '[]', '{}', '{}')"
                ),
                {"v": version, "a": active},
            )
    command.upgrade(alembic_config(url), "head")
    with Session(get_engine(url)) as s:
        line = s.exec(select(m.ModelLine)).one()
        assert line.slug == "default" and line.last_revision == 2
        rows = s.exec(select(m.FittedModel).order_by(m.FittedModel.version)).all()  # type: ignore[arg-type]
        assert all(r.paint_batches == {} for r in rows)  # 0007: nothing recorded for old models
        assert [(r.version, r.revision, r.line_id, r.label) for r in rows] == [
            (3, 1, line.id, ""),
            (5, 2, line.id, ""),
        ]
    command.downgrade(alembic_config(url), "0003")
    with get_engine(url).connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM fitted_model")).scalar_one() == 2


def test_model_line_migration_empty_database(tmp_path: Path) -> None:
    """With no models, 0004 creates no line (the first fit creates "default")."""
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    migrate(url)
    with Session(get_engine(url)) as s:
        assert s.exec(select(m.ModelLine)).first() is None
