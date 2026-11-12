from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from paintmixer.api.app import create_app
from paintmixer.config import Settings
from paintmixer.db import models as m
from paintmixer.db.session import get_engine, migrate

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


def test_stored_batch_above_default_max_raises_the_max(tmp_path: Path) -> None:
    """Settings saved before machine_max_batch_ml existed (here a 400 ml batch) still load:
    the maximum is raised to the stored batch instead of every endpoint failing."""
    url = f"sqlite:///{tmp_path / 'old.db'}"
    migrate(url)
    with Session(get_engine(url)) as s:
        s.add(m.Setting(key="app", value={"batch_volume_ml": 400}))
        s.commit()
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as c:
        r = c.get(f"{API}/settings")
        assert r.status_code == 200, r.text
        assert r.json()["batch_volume_ml"] == 400 and r.json()["machine_max_batch_ml"] == 400
        assert c.get(f"{API}/machine").status_code == 200
        # a new batch above the (raised) maximum is still refused
        r = c.patch(f"{API}/settings", json={"machine_max_batch_ml": 250})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_settings"
        # the next change persists the raised maximum
        r = c.patch(f"{API}/settings", json={"low_level_warn_pct": 20})
        assert r.status_code == 200 and r.json()["machine_max_batch_ml"] == 400
    with Session(get_engine(url)) as s:
        row = s.get(m.Setting, "app")
        assert row is not None and row.value["machine_max_batch_ml"] == 400


def test_observer_and_geometry_are_read_only(client: TestClient) -> None:
    s = client.get(f"{API}/settings").json()
    assert s["observer"] == "CIE 1931 2°" and s["geometry"].startswith("45/0")
    assert s["read_only"] == ["observer", "geometry"]
    r = client.patch(f"{API}/settings", json={"observer": "CIE 1964 10°"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.patch(f"{API}/settings", json={"top_n": 4})
    assert r.status_code == 200 and r.json()["observer"] == "CIE 1931 2°"
    client.patch(f"{API}/settings", json={"top_n": 5})


def test_max_paints_is_bound_by_the_model(fitted_client: TestClient) -> None:
    c = fitted_client
    n = len(c.get(f"{API}/models/active").json()["paint_ids"])
    assert c.get(f"{API}/settings").json()["max_paints"] == 4
    # up to the model's paint count is allowed, more is refused
    r = c.patch(f"{API}/settings", json={"max_paints": n})
    assert r.status_code == 200 and r.json()["max_paints"] == n
    try:
        r = c.patch(f"{API}/settings", json={"max_paints": n + 1})
        assert r.status_code == 422 and r.json()["error"]["code"] == "bad_constraints"
        assert r.json()["error"]["details"]["paints_in_model"] == n
        body = {"target": {"lab": [60, -10, 15]}, "top_n": 1}
        r = c.post(f"{API}/solve", json={**body, "max_paints": n + 1})
        assert r.status_code == 422 and r.json()["error"]["code"] == "bad_constraints"
        r = c.post(f"{API}/solve", json={**body, "max_paints": n, "min_fraction": 0.0})
        assert r.status_code == 200, r.text
        r = c.get(f"{API}/gamut", params={"max_paints": n + 1})
        assert r.status_code == 422 and r.json()["error"]["code"] == "bad_constraints"
    finally:
        c.patch(f"{API}/settings", json={"max_paints": 4})
