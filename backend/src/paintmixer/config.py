"""Runtime settings (environment variables prefixed ``PAINTMIXER_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_db_url() -> str:
    data_dir = Path(os.environ.get("PAINTMIXER_DATA_DIR", Path.cwd() / "var"))
    return f"sqlite:///{data_dir / 'paintmixer.db'}"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get("PAINTMIXER_DATABASE_URL", _default_db_url())
    )
    currency: str = field(default_factory=lambda: os.environ.get("PAINTMIXER_CURRENCY", "SGD"))
    seed: int = field(default_factory=lambda: int(os.environ.get("PAINTMIXER_SEED", "1234")))


def get_settings() -> Settings:
    return Settings()
