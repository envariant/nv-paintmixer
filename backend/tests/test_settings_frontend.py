from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def test_new_settings_defaults_and_validation(client: TestClient) -> None:
    s = client.get(f"{API}/settings").json()
    assert s["machine_max_batch_ml"] == 250
    assert s["accept_tolerance_de"] == 1.0
    assert s["check_illuminants"] == ["A", "F11"]
    assert s["low_level_warn_pct"] == 25
    r = client.patch(f"{API}/settings", json={"batch_volume_ml": 300})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_settings"
    r = client.patch(f"{API}/settings", json={"check_illuminants": ["A", "D50"]})
    assert r.status_code == 200 and r.json()["check_illuminants"] == ["A", "D50"]


def test_solve_reports_metamerism_under_checked_lights(fitted_client: TestClient) -> None:
    c = fitted_client
    c.patch(f"{API}/settings", json={"check_illuminants": ["A", "D50", "LED-B3"]})
    try:
        sol = c.post(
            f"{API}/solve", json={"target": {"lab": [60, -10, 15], "name": "T"}, "top_n": 1}
        ).json()
        assert set(sol["candidates"][0]["metamerism"]) == {"A", "D50", "LED-B3"}
    finally:
        c.patch(f"{API}/settings", json={"check_illuminants": ["A", "F11"]})


def test_volume_cap_enforced(fitted_client: TestClient) -> None:
    c = fitted_client
    r = c.post(
        f"{API}/solve",
        json={"target": {"lab": [60, -10, 15], "name": "T"}, "batch_volume_ml": 400},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "batch_too_large"
