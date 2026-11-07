"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from paintmixer import __version__
from paintmixer.api.errors import install_error_handlers
from paintmixer.api.routers import calibration, colors, mixing, models, paints, system, worksheet
from paintmixer.config import Settings, get_settings
from paintmixer.db.session import migrate

API_PREFIX = "/api/v1"

DESCRIPTION = """
PaintMixer computes paint-mixing recipes with a Kubelka-Munk model fitted from
spectrophotometer drawdowns.

* **Paints**: library paints (calibrated) and loaded paints (on dispenser channels).
* **Calibration**: worksheet → measure → upload CSV → validate → fit (background) → model versions.
* **Mixing**: `POST /solve` ranked recipes, `POST /predict` forward model, `GET /gamut`.

Errors use `{"error": {"code", "message", "details"}}`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        migrate(cfg.database_url)
        yield

    app = FastAPI(
        title="PaintMixer API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.settings = cfg
    install_error_handlers(app)
    for r in (system, paints, colors, worksheet, calibration, models, mixing):
        app.include_router(r.router, prefix=API_PREFIX)
    return app


app = create_app()
