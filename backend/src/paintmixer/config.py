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
    # Seed the CMYKW demo (paintmixer.demo) on startup when the database is empty.
    seed_demo: bool = field(
        default_factory=lambda: (
            os.environ.get("PAINTMIXER_SEED_DEMO", "").lower() in ("1", "true", "yes")
        )
    )
    # Recompute library match summaries in the background when a model is activated or solver
    # inputs change (api.matches). Off: they are only computed when asked for.
    match_cache_auto: bool = field(
        default_factory=lambda: (
            os.environ.get("PAINTMIXER_MATCH_CACHE_AUTO", "1").lower() not in ("0", "false", "no")
        )
    )
    # Worker processes for solve/gamut/fit. 0 = run in the FastAPI thread pool instead.
    compute_workers: int = field(
        default_factory=lambda: int(os.environ.get("PAINTMIXER_COMPUTE_WORKERS", "2"))
    )


def get_settings() -> Settings:
    return Settings()
