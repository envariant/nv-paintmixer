"""Model lines (named series of versions) and model refs (12, line, line@3, line@latest)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from paintmixer.api.app import create_app
from paintmixer.api.lines import slugify
from paintmixer.config import Settings
from paintmixer.demo import seed_demo
from tests.api_helpers import fit

API = "/api/v1"


@pytest.fixture
def c(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """Fresh demo database per test: cmykw-demo@1 = v1 (calibrated, active), @2 = v2 (swatches)."""
    url = f"sqlite:///{tmp_path_factory.mktemp('lines') / 'db.sqlite'}"
    seed_demo(url)
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as client:
        yield client


def _ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def _code(r: Any) -> str:
    return str(r.json()["error"]["code"])


def test_slugify() -> None:
    assert slugify("Oil set — 2026") == "oil-set-2026"
    assert slugify("2026 acrylics") == "line-2026-acrylics"
    assert slugify("!!!") == "line"


def test_demo_line_and_refs(c: TestClient) -> None:
    (line,) = _ok(c.get(f"{API}/model-lines"))
    assert line["slug"] == "cmykw-demo" and line["n_versions"] == 2
    # the bare line id means the newest *calibrated* revision, not the newer swatch model
    assert (line["current_version"], line["current_ref"], line["active_version"]) == (
        1,
        "cmykw-demo@1",
        1,
    )
    for ref, version in [
        ("1", 1),
        ("cmykw-demo", 1),
        ("cmykw-demo@2", 2),
        ("cmykw-demo@latest", 2),
    ]:
        got = _ok(c.get(f"{API}/models/{ref}"))
        assert got["version"] == version, ref
    v2 = _ok(c.get(f"{API}/models/2"))
    assert (v2["ref"], v2["line"], v2["revision"]) == ("cmykw-demo@2", "cmykw-demo", 2)
    assert v2["label"] == "From swatch colours" and v2["line_name"] == "CMYKW demo (synthetic)"
    for ref in ("9", "nope", "cmykw-demo@9"):
        assert c.get(f"{API}/models/{ref}").status_code == 404, ref
    assert _code(c.get(f"{API}/models/cmykw-demo@x")) == "invalid_ref"
    # refs work on every model endpoint
    assert _ok(c.get(f"{API}/models/cmykw-demo/gamut"))["model_version"] == 1
    sp = _ok(c.get(f"{API}/models/cmykw-demo/spectra?reference_version=cmykw-demo@2"))
    assert sp["version"] == 1 and sp["reference_version"] == 2
    assert [m["version"] for m in _ok(c.get(f"{API}/models?line=cmykw-demo"))] == [2, 1]
    assert c.get(f"{API}/models?line=nope").status_code == 404


def test_activate_by_ref(c: TestClient) -> None:
    got = _ok(c.post(f"{API}/models/cmykw-demo@2/activate"))
    assert got["version"] == 2 and got["active"]
    assert [m["version"] for m in _ok(c.get(f"{API}/models")) if m["active"]] == [2]
    assert _ok(c.get(f"{API}/model-lines/cmykw-demo"))["active_version"] == 2
    assert _ok(c.get(f"{API}/models/active"))["ref"] == "cmykw-demo@2"


def test_create_rename_and_delete_lines(c: TestClient) -> None:
    line = _ok(c.post(f"{API}/model-lines", json={"name": "Oil set — 2026"}), 201)
    assert line["slug"] == "oil-set-2026" and line["versions"] == []
    assert line["current_version"] is None and line["active_version"] is None
    assert _code(c.post(f"{API}/model-lines", json={"name": "Oil set 2026"})) == "line_exists"
    for slug in ("active", "9-lives", "Bad Slug"):
        r = c.post(f"{API}/model-lines", json={"name": "x", "slug": slug})
        assert _code(r) == "invalid_slug", slug
    renamed = _ok(
        c.patch(f"{API}/model-lines/oil-set-2026", json={"name": "Oils", "description": "d"})
    )
    assert (renamed["slug"], renamed["name"], renamed["description"]) == (
        "oil-set-2026",
        "Oils",
        "d",
    )
    assert c.delete(f"{API}/model-lines/oil-set-2026").status_code == 204
    assert c.get(f"{API}/model-lines/oil-set-2026").status_code == 404
    r = c.delete(f"{API}/model-lines/cmykw-demo")
    assert r.status_code == 409 and _code(r) == "line_not_empty"


def test_swatch_model_into_line_then_move(c: TestClient) -> None:
    _ok(c.post(f"{API}/model-lines", json={"name": "Trial", "slug": "trial"}), 201)
    r = c.post(f"{API}/models/from-swatches", json={"line": "nope", "activate": False})
    assert _code(r) == "unknown_line"
    res = _ok(
        c.post(
            f"{API}/models/from-swatches",
            json={"line": "trial", "label": "first look", "activate": False},
        ),
        201,
    )
    m = res["model"]
    assert (m["version"], m["ref"], m["label"], m["active"]) == (3, "trial@1", "first look", False)
    # a line with only uncalibrated versions resolves to its newest
    assert _ok(c.get(f"{API}/models/trial"))["version"] == 3
    moved = _ok(
        c.patch(f"{API}/models/trial@1", json={"line": "cmykw-demo", "label": "kept", "notes": "n"})
    )
    assert (moved["version"], moved["ref"], moved["label"], moved["notes"]) == (
        3,
        "cmykw-demo@3",
        "kept",
        "n",
    )
    assert _ok(c.get(f"{API}/model-lines/trial"))["n_versions"] == 0
    # moving within the same line is a no-op; unknown target line is a 404
    assert _ok(c.patch(f"{API}/models/3", json={"line": "cmykw-demo"}))["ref"] == "cmykw-demo@3"
    assert c.patch(f"{API}/models/3", json={"line": "nope"}).status_code == 404
    # revisions are never reused: a later model in "trial" is @2
    again = _ok(
        c.post(f"{API}/models/from-swatches", json={"line": "trial", "activate": False}), 201
    )
    assert again["model"]["ref"] == "trial@2"


def test_fit_into_line_and_default_line(c: TestClient) -> None:
    assert _code(c.post(f"{API}/calibration/fit", json={"line": "nope"})) == "unknown_line"
    _ok(c.post(f"{API}/model-lines", json={"name": "Studio", "slug": "studio"}), 201)
    run = fit(c, line="studio", label="first studio fit", activate=False)
    assert run["status"] == "succeeded" and "studio@1" in run["message"]
    got = _ok(c.get(f"{API}/models/studio"))
    assert (got["label"], got["source"], got["active"]) == (
        "first studio fit",
        "calibration",
        False,
    )
    # no line given: the auto-created "default" line
    run = fit(c, activate=False)
    assert run["status"] == "succeeded"
    assert _ok(c.get(f"{API}/models/default"))["ref"] == "default@1"
    slugs = [ln["slug"] for ln in _ok(c.get(f"{API}/model-lines"))]
    assert slugs == ["cmykw-demo", "default", "studio"]
