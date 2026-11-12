from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api_helpers import dispense

API = "/api/v1"


def test_refill_and_level(client: TestClient) -> None:
    r = client.post(
        f"{API}/paints",
        json={
            "id": "pg7",
            "name": "Phthalo Green",
            "pigment_code": "PG7",
            "capacity_ml": 250,
            "batch_code": "C0401",
            "body_type": "Fluid",
        },
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["level_ml"] is None and p["level_pct"] is None and not p["low"]
    p = client.post(f"{API}/paints/pg7/refill", json={}).json()
    assert p["level_ml"] == 250 and p["level_pct"] == 100 and p["last_refill_at"]
    p = client.post(f"{API}/paints/pg7/refill", json={"level_ml": 45, "batch_code": "C0402"}).json()
    assert p["level_pct"] == 18 and p["low"] and p["batch_code"] == "C0402"
    r = client.post(f"{API}/paints/pg7/refill", json={"level_ml": 300})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_capacity"


def test_model_colour_and_dispense_decrements(fitted_client: TestClient) -> None:
    c = fitted_client
    paints = c.get(f"{API}/paints").json()
    calibrated = [p for p in paints if p["calibrated"]]
    assert calibrated and all(p["model_hex"] and len(p["model_lab"]) == 3 for p in calibrated)
    for p in calibrated:
        c.patch(f"{API}/paints/{p['id']}", json={"capacity_ml": 500})
        c.post(f"{API}/paints/{p['id']}/refill", json={})
    sol = c.post(f"{API}/solve", json={"target": {"lab": [60, -10, 15], "name": "T"}}).json()
    comps = {x["paint_id"]: x["fraction"] for x in sol["candidates"][0]["components"]}
    job = c.post(
        f"{API}/jobs",
        json={
            "target": {"lab": [60, -10, 15], "name": "T"},
            "components": comps,
            "batch_volume_ml": 100,
        },
    ).json()
    dispense(c, job["id"], simulate=True)
    after = {p["id"]: p for p in c.get(f"{API}/paints").json()}
    used = sum(500 - after[pid]["level_ml"] for pid in comps)
    assert 95 < used < 105
