from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import SAMPLE_DATA


def import_paints(client: TestClient) -> dict[str, Any]:
    with (SAMPLE_DATA / "paints.csv").open("rb") as fh:
        r = client.post("/api/v1/paints/import", files={"file": ("paints.csv", fh, "text/csv")})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def upload_calibration(
    client: TestClient, name: str = "calibration_starter5.csv"
) -> dict[str, Any]:
    with (SAMPLE_DATA / name).open("rb") as fh:
        r = client.post("/api/v1/calibration/upload", files={"file": (name, fh, "text/csv")})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def fit(client: TestClient, **body: Any) -> dict[str, Any]:
    r = client.post("/api/v1/calibration/fit", json=body)
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    for _ in range(600):
        run: dict[str, Any] = client.get(f"/api/v1/calibration/fits/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("fit did not finish")
