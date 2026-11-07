"""Alembic environment: uses SQLModel metadata and batch mode for SQLite."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import paintmixer.db.models  # noqa: F401  (registers tables)
from paintmixer.config import get_settings

config = context.config
if config.config_file_name is not None and config.get_main_option("configure_logging", "1") == "1":
    from logging.config import fileConfig

    fileConfig(config.config_file_name, disable_existing_loggers=False)

url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
