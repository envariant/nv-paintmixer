"""Per-paint calibration accuracy: GET /models/{ref}/paint-accuracy (Models rack)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from paintmixer.api.app import create_app
from paintmixer.calibration.accuracy import (
    PaintCoverage,
    PaintQuality,
    SampleError,
    grade,
    paint_status,
)
from paintmixer.config import Settings
from paintmixer.demo import seed_demo

API = "/api/v1"
OK = PaintCoverage(has_masstone=True, has_tint=True, n_mixture_drawdowns=5)
SHORT = PaintCoverage(has_masstone=True, has_tint=True, n_mixture_drawdowns=1)


def _q(coverage: PaintCoverage, *des: float) -> PaintQuality:
    return PaintQuality(
        "p", coverage, [SampleError(f"S{i}", d, False, False) for i, d in enumerate(des)]
    )


def test_grade_bounds() -> None:
    assert [grade(x) for x in (0.0, 0.39, 0.4, 0.99, 1.0, 1.99, 2.0, 9.0)] == [
        "excellent",
        "excellent",
        "good",
        "good",
        "fair",
        "fair",
        "poor",
        "poor",
    ]


def test_status_most_pressing_first() -> None:
    assert paint_status(None, batch_changed=True) == "uncalibrated"
    assert paint_status(_q(OK), batch_changed=False) == "uncalibrated"  # no samples
    assert paint_status(_q(SHORT, 3.0), batch_changed=True) == "stale"
    assert paint_status(_q(SHORT, 3.0), batch_changed=False) == "needs_samples"
    assert paint_status(_q(OK, 0.3, 2.0), batch_changed=False) == "review"
    assert paint_status(_q(OK, 0.3, 1.99), batch_changed=False) == "ok"


@pytest.fixture
def demo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path_factory.mktemp('acc') / 'db.sqlite'}"
    seed_demo(url)
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as c:
        yield c


def _by_paint(c: TestClient, ref: str) -> dict[str, dict]:  # type: ignore[type-arg]
    r = c.get(f"{API}/models/{ref}/paint-accuracy")
    assert r.status_code == 200, r.text
    return {p["paint_id"]: p for p in r.json()}


def test_every_model_paint_appears(demo: TestClient) -> None:
    fm = demo.get(f"{API}/models/cmykw-demo@1").json()
    r = demo.get(f"{API}/models/cmykw-demo@1/paint-accuracy").json()
    assert [p["paint_id"] for p in r] == fm["paint_ids"]
    for p in r:
        assert p["samples"] and p["coverage"]["ok"]
        assert p["calibrated_at"] == fm["created_at"]
        assert p["grade"] == grade(p["median_de"])
        assert p["status"] in ("ok", "review")
        assert (p["status"] == "review") == any(s["de2000"] >= 2.0 for s in p["samples"])
    assert demo.get(f"{API}/models/99/paint-accuracy").status_code == 404


def test_batch_change_after_the_fit_marks_the_paint_stale(demo: TestClient) -> None:
    # demo paints have no batch recorded: setting one is not a change of lot
    demo.patch(f"{API}/paints/phthalo-blue", json={"batch_code": "C0401"})
    assert _by_paint(demo, "1")["phthalo-blue"]["status"] != "stale"
    # a model made now records C0401; a new lot after that makes it stale
    demo.post(f"{API}/calibration/fit", json={"line": "cmykw-demo", "activate": False})
    fresh = _by_paint(demo, "cmykw-demo@latest")
    assert fresh["phthalo-blue"]["batch_at_fit"] == "C0401"
    assert fresh["phthalo-blue"]["status"] != "stale"
    demo.post(f"{API}/paints/phthalo-blue/refill", json={"level_ml": 0, "batch_code": "C0402"})
    after = _by_paint(demo, "cmykw-demo@latest")
    assert after["phthalo-blue"]["status"] == "stale"
    assert (after["phthalo-blue"]["batch_at_fit"], after["phthalo-blue"]["batch_now"]) == (
        "C0401",
        "C0402",
    )
    assert all(p["status"] != "stale" for pid, p in after.items() if pid != "phthalo-blue")


def test_swatch_model_paints_are_uncalibrated(demo: TestClient) -> None:
    r = _by_paint(demo, "cmykw-demo@2")
    assert {p["status"] for p in r.values()} == {"uncalibrated"}
    assert all(
        p["samples"] == [] and p["grade"] is None and p["coverage"] is None for p in r.values()
    )
