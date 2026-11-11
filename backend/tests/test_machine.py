from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"
LAB = [60.0, -10.0, 15.0]


def _job(c: TestClient, name: str) -> dict:  # type: ignore[type-arg]
    sol = c.post(f"{API}/solve", json={"target": {"lab": LAB, "name": name}}).json()
    comps = {x["paint_id"]: x["fraction"] for x in sol["candidates"][0]["components"]}
    r = c.post(
        f"{API}/jobs",
        json={"target": {"lab": LAB, "name": name}, "components": comps, "batch_volume_ml": 100},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_machine_pill_accept_and_cancel(fitted_client: TestClient) -> None:
    c = fitted_client
    assert c.get(f"{API}/machine").json()["label"] == "Machine ready"

    j = _job(c, "Plum Mist")
    c.post(f"{API}/jobs/{j['id']}/dispense", json={"simulate": True})
    st = c.get(f"{API}/machine").json()
    assert st["state"] == "measuring" and st["current_job"]["name"] == "Plum Mist"
    assert st["label"] == "Measuring · Plum Mist" and st["current_job"]["poured_ml"] > 95

    # accept needs a measurement
    r = c.post(f"{API}/jobs/{j['id']}/accept")
    assert r.status_code == 409
    c.post(f"{API}/jobs/{j['id']}/measurement", json={"simulate": True, "seed": 1})
    assert c.post(f"{API}/jobs/{j['id']}/accept").json()["status"] == "accepted"

    k = _job(c, "Harbour Fog")
    c.post(f"{API}/jobs/{k['id']}/dispense", json={"simulate": True})
    out = c.post(f"{API}/jobs/{k['id']}/cancel", json={"reason": "wrong cup"}).json()
    assert out["status"] == "cancelled" and out["corrections"][-1]["poured_ml"] > 95
    assert c.post(f"{API}/jobs/{k['id']}/cancel", json={}).status_code == 409

    st = c.get(f"{API}/machine").json()
    assert st["label"] == "Machine ready" and st["current_job"] is None
    assert [b["name"] for b in st["recent"][:2]] == ["Harbour Fog", "Plum Mist"]
    assert st["recent"][1]["last_de"] is not None and st["recent"][1]["target_hex"].startswith("#")


def test_correct_uses_settings_tolerance(fitted_client: TestClient) -> None:
    c = fitted_client
    c.patch(f"{API}/settings", json={"accept_tolerance_de": 5})
    try:
        j = _job(c, "Loose")
        c.post(f"{API}/jobs/{j['id']}/dispense", json={"simulate": True})
        c.post(f"{API}/jobs/{j['id']}/measurement", json={"simulate": True, "seed": 2})
        assert c.post(f"{API}/jobs/{j['id']}/correct", json={}).json()["status"] == "done"
    finally:
        c.patch(f"{API}/settings", json={"accept_tolerance_de": 1})
