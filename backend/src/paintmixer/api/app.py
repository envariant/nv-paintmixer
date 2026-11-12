"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from paintmixer import __version__
from paintmixer.api import matches
from paintmixer.api.compute import make_executor
from paintmixer.api.errors import install_error_handlers
from paintmixer.api.routers import (
    calibration,
    colors,
    illuminants,
    jobs,
    lines,
    machine,
    mixing,
    models,
    paints,
    palettes,
    system,
    worksheet,
)
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
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        migrate(cfg.database_url)
        if cfg.seed_demo:
            from paintmixer.demo import database_is_empty, seed_demo

            if database_is_empty(cfg.database_url):
                seed_demo(cfg.database_url)
        app_.state.executor = make_executor(cfg.compute_workers)
        app_.state.loop = asyncio.get_running_loop()  # for matches.request_refresh
        try:
            yield
        finally:
            await matches.stop(app_)
            app_.state.loop = None
            if app_.state.executor is not None:
                app_.state.executor.shutdown(wait=False, cancel_futures=True)

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
    app.state.executor = None
    app.state.loop = None
    app.state.match_task = None
    app.state.match_failed = set()  # api.matches: inputs whose solve failed
    install_error_handlers(app)
    for r in (
        system,
        illuminants,
        paints,
        colors,
        palettes,
        worksheet,
        calibration,
        models,
        lines,
        mixing,
        jobs,
        machine,
    ):
        app.include_router(r.router, prefix=API_PREFIX)
    return app


app = create_app()
