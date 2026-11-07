from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paintmixer.domain import PaintInfo
from tests.helpers import load_paints_csv


@pytest.fixture
def paints() -> dict[str, PaintInfo]:
    return load_paints_csv()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from paintmixer.api.app import create_app
    from paintmixer.config import Settings

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}", compute_workers=0))
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def fitted_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """Client with paints imported and the starter-5 sample calibration fitted (shared)."""
    from paintmixer.api.app import create_app
    from paintmixer.config import Settings
    from tests.api_helpers import fit, import_paints, upload_calibration

    db = tmp_path_factory.mktemp("fitted") / "api.db"
    app = create_app(Settings(database_url=f"sqlite:///{db}", compute_workers=0))
    with TestClient(app) as c:
        import_paints(c)
        upload_calibration(c)
        run = fit(c)
        assert run["status"] == "succeeded", run
        yield c
