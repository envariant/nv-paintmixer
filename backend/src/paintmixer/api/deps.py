"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlmodel import Session

from paintmixer.config import Settings
from paintmixer.db.session import get_engine


def get_config(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    settings: Settings = request.app.state.settings
    with Session(get_engine(settings.database_url)) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
ConfigDep = Annotated[Settings, Depends(get_config)]
