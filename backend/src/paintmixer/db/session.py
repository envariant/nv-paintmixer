"""Engine/session helpers and programmatic migrations."""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache
from pathlib import Path

from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


@cache
def get_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _rec) -> None:  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def alembic_config(url: str):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate(url: str) -> None:
    """Upgrade the database at ``url`` to the latest Alembic revision."""
    from alembic import command

    get_engine(url)  # ensures directory exists
    command.upgrade(alembic_config(url), "head")


def session_scope(url: str) -> Iterator[Session]:
    with Session(get_engine(url)) as session:
        yield session
