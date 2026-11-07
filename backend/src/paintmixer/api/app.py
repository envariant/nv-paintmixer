"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from paintmixer import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="PaintMixer API", version=__version__)

    @app.get("/api/v1/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
