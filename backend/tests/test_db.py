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
