"""Demo seeding (CMYKW starter set) and per-model gamut endpoints, which the demo's two models
(calibrated v1, swatch-derived v2) exercise."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from paintmixer.api.app import create_app
from paintmixer.cli import app as cli_app
from paintmixer.config import Settings
from paintmixer.demo import DEMO_PAINTS, database_is_empty, seed_demo

API = "/api/v1"
CMYKW = {"titanium-white", "carbon-black", "phthalo-blue", "quinacridone-magenta", "arylide-yellow"}


@pytest.fixture(scope="module")
def demo_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    url = f"sqlite:///{tmp_path_factory.mktemp('demo') / 'demo.db'}"
    rep = seed_demo(url)
    assert rep.errors == []
    return url


@pytest.fixture(scope="module")
def demo_client(demo_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(database_url=demo_url, compute_workers=0))) as c:
        yield c


def test_seeded_state(demo_client: TestClient) -> None:
    paints = {p["id"]: p for p in demo_client.get(f"{API}/paints").json()}
    assert set(paints) == CMYKW == set(DEMO_PAINTS)
    assert all(p["loaded"] for p in paints.values())
    models = demo_client.get(f"{API}/models").json()
    by_v = {mo["version"]: mo for mo in models}
    assert by_v[1]["source"] == "calibration" and by_v[1]["active"]
    assert by_v[2]["source"] == "swatches" and not by_v[2]["active"]
    assert sum(mo["active"] for mo in models) == 1
    assert set(by_v[1]["paint_ids"]) == CMYKW
    assert len(demo_client.get(f"{API}/colors").json()) > 0
    # the active model solves straight away
    r = demo_client.post(f"{API}/solve", json={"target": {"hex": "#4a7a9c"}})
    assert r.status_code == 200 and r.json()["candidates"][0]["de2000"] < 3.0


def test_seed_is_idempotent_and_refit_adds_versions(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'd.db'}"
    assert database_is_empty(url)
    first = seed_demo(url)
    assert (first.calibrated_version, first.swatch_version, first.active_version) == (1, 2, 1)
    assert not database_is_empty(url)
    again = seed_demo(url)
    assert (again.calibrated_version, again.swatch_version) == (1, 2)
    assert again.samples_replaced == first.samples_stored and again.colours_created == 0
    assert len(again.skipped) == 2
    refit = seed_demo(url, refit=True)
    assert (refit.calibrated_version, refit.swatch_version, refit.active_version) == (3, 4, 3)
    assert "calibrated model: v3 (active)" in refit.summary()


def test_seed_missing_sample_data(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="sample data not found"):
        seed_demo(f"sqlite:///{tmp_path / 'x.db'}", tmp_path)


def test_auto_seed_only_when_empty(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'auto.db'}"
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as c:
        assert c.get(f"{API}/models").json() == []  # flag off: nothing seeded
    cfg = Settings(database_url=url, compute_workers=0, seed_demo=True)
    with TestClient(create_app(cfg)) as c:
        assert [mo["version"] for mo in c.get(f"{API}/models").json()] == [2, 1]
        c.post(f"{API}/models/2/activate")
    with TestClient(create_app(cfg)) as c:  # not empty: left alone
        models = c.get(f"{API}/models").json()
        assert len(models) == 2 and next(mo for mo in models if mo["active"])["version"] == 2


def test_cli_seed_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAINTMIXER_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    res = CliRunner().invoke(cli_app, ["seed-demo"])
    assert res.exit_code == 0, res.output
    assert "calibrated model: v1 (active)" in res.output and "v2" in res.output


# --- gamut of any model version -------------------------------------------------------------


def test_model_gamut_any_version(demo_client: TestClient) -> None:
    g1 = demo_client.get(f"{API}/models/1/gamut").json()
    g2 = demo_client.get(f"{API}/models/2/gamut").json()
    assert set(g1["pool"]) == CMYKW == set(g2["pool"])  # default: every paint in the model
    assert (g1["model_version"], g1["model_source"]) == (1, "calibration")
    assert (g2["model_version"], g2["model_source"]) == (2, "swatches")
    assert g1["max_paints"] >= 3
    sl = g1["slices"][len(g1["slices"]) // 2]
    assert len(sl["hex"]) == len(sl["chroma"]) == 36
    assert all((h is None) == (c == 0) for h, c in zip(sl["hex"], sl["chroma"], strict=True))
    assert all(h is None or (h.startswith("#") and len(h) == 7) for h in sl["hex"])
    # the two versions describe different reachability
    assert max(max(s["chroma"]) for s in g1["slices"]) != max(
        max(s["chroma"]) for s in g2["slices"]
    )
    # active-model endpoint agrees with the per-version one and carries the same fields
    active = demo_client.get(f"{API}/gamut").json()
    assert active["model_version"] == 1 and "hex" in active["slices"][0]


def test_model_gamut_pool_and_errors(demo_client: TestClient) -> None:
    r = demo_client.get(
        f"{API}/models/2/gamut",
        params={"pool": "titanium-white,phthalo-blue", "max_paints": 2},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["pool"] == ["titanium-white", "phthalo-blue"] and j["max_paints"] == 2
    r = demo_client.get(f"{API}/models/99/gamut")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = demo_client.get(f"{API}/models/1/gamut", params={"pool": "titanium-white,nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_paint"


def test_model_gamut_svg(demo_client: TestClient) -> None:
    r = demo_client.get(f"{API}/models/2/gamut.svg", params={"chroma_scale": 60, "columns": 3})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(r.text)
    ns = "{http://www.w3.org/2000/svg}"
    panels = root.findall(f"{ns}svg")
    n_slices = len(demo_client.get(f"{API}/models/2/gamut").json()["slices"])
    assert len(panels) == n_slices and panels[0].get("data-L") is not None
    assert "model v2 (swatches)" in (root.findtext(f"{ns}title") or "")
    assert "scale ±60" in r.text
    assert demo_client.get(f"{API}/models/99/gamut.svg").status_code == 404
