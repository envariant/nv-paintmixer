"""Library match summaries (api.matches): cached closest mix per colour, background refresh,
GET /colors?with_match=true and GET /palettes/{id}/summary."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from paintmixer.api import matches
from paintmixer.api.app import create_app
from paintmixer.config import Settings
from paintmixer.db.session import get_engine
from paintmixer.demo import seed_demo

API = "/api/v1"
KEEP = ("Sage", "Plum", "Harbour Fog")  # a small library keeps these tests fast


def _client(url: str, auto: bool) -> TestClient:
    return TestClient(
        create_app(Settings(database_url=url, compute_workers=0, match_cache_auto=auto))
    )


def _seed(tmp_path_factory: pytest.TempPathFactory, keep: tuple[str, ...] | None) -> str:
    url = f"sqlite:///{tmp_path_factory.mktemp('lib') / 'db.sqlite'}"
    seed_demo(url)
    if keep is not None:
        with _client(url, auto=False) as c:
            for e in c.get(f"{API}/colors").json():
                c.delete(f"{API}/colors/{e['id']}")
            for name, lab in zip(keep, ([60, -10, 15], [45, 30, -20], [70, -4, -8]), strict=True):
                assert c.post(f"{API}/colors", json={"name": name, "lab": lab}).status_code == 201
    return url


def _wait_all(c: TestClient, timeout: float) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while True:
        out: list[dict[str, Any]] = c.get(f"{API}/colors", params={"with_match": True}).json()
        if all(e["match"] is not None for e in out):
            return out
        assert time.monotonic() < deadline, [e["name"] for e in out if e["match"] is None]
        time.sleep(0.2)


def _todo(url: str) -> list[int]:
    with Session(get_engine(url)) as s:
        p = matches.plan(s)
        assert p is not None
        return [cid for cid, _h, _t in p.todo]


@pytest.fixture
def small(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _seed(tmp_path_factory, KEEP)


def test_activation_fills_matches_and_palette_summary_agrees(small: str) -> None:
    with _client(small, auto=True) as c:
        assert c.post(f"{API}/models/cmykw-demo@1/activate").status_code == 200
        lib = _wait_all(c, timeout=60)
        for e in lib:
            mt = e["match"]
            assert mt["model_version"] == 1 and mt["reach"] in ("within", "uncertain", "out")
            assert mt["de"] >= 0 and mt["n_paints"] == len(mt["best_components"]) >= 1
            assert abs(sum(x["fraction"] for x in mt["best_components"]) - 1) < 1e-5
            assert mt["cost_per_250ml"] > 0 and mt["uncertainty_de"] is not None
        # the cached match is the closest mix /solve finds with the same settings
        sage = next(e for e in lib if e["name"] == "Sage")
        sol = c.post(f"{API}/solve", json={"target": {"library_id": sage["id"]}}).json()
        closest = next(x for x in sol["candidates"] if "closest" in x["tags"])
        assert sage["match"]["de"] == pytest.approx(closest["de2000"], abs=1e-3)
        # palette band = the per-colour values
        ids = [e["id"] for e in lib]
        pal = c.post(f"{API}/palettes", json={"name": "P", "color_ids": ids}).json()
        summ = c.get(f"{API}/palettes/{pal['id']}/summary").json()
        reaches = [e["match"]["reach"] for e in lib]
        assert summ == {
            "n": 3,
            "within": reaches.count("within"),
            "uncertain": reaches.count("uncertain"),
            "out": reaches.count("out"),
            "pending": 0,
            "worst_de": max(e["match"]["de"] for e in lib),
        }


def test_matches_go_stale_when_inputs_change(small: str) -> None:
    with _client(small, auto=False) as c:  # no proactive refresh: only asking computes
        assert all(
            e["match"] is None for e in c.get(f"{API}/colors", params={"with_match": True}).json()
        )
        lib = _wait_all(c, timeout=60)  # that request started a refresh
        assert _todo(small) == []
        sage = next(e for e in lib if e["name"] == "Sage")
        # a colour change makes only that colour stale
        c.patch(f"{API}/colors/{sage['id']}", json={"lab": [58, -12, 16]})
        assert _todo(small) == [sage["id"]]
        # a renamed colour keeps its match
        c.patch(f"{API}/colors/{sage['id']}", json={"name": "Sage 2"})
        assert _todo(small) == [sage["id"]]
        # solver settings, the paint pool and the active model change every match
        c.patch(f"{API}/settings", json={"top_n": 4})
        assert sorted(_todo(small)) == sorted(e["id"] for e in lib)
        c.patch(f"{API}/settings", json={"top_n": 5})
        c.post(f"{API}/models/cmykw-demo@2/activate")
        assert sorted(_todo(small)) == sorted(e["id"] for e in lib)
        summ = c.get(
            f"{API}/palettes/{c.post(f'{API}/palettes', json={'name': 'Q', 'color_ids': [sage['id']]}).json()['id']}/summary"
        ).json()
        assert summ["pending"] == 1 and summ["worst_de"] is None


def test_no_matches_without_an_active_model(tmp_path_factory: pytest.TempPathFactory) -> None:
    url = f"sqlite:///{tmp_path_factory.mktemp('empty') / 'db.sqlite'}"
    with _client(url, auto=True) as c:
        cid = c.post(f"{API}/colors", json={"name": "Red", "hex": "#cc2222"}).json()["id"]
        assert c.get(f"{API}/colors", params={"with_match": True}).json()[0]["match"] is None
        pal = c.post(f"{API}/palettes", json={"name": "P", "color_ids": [cid]}).json()
        summ = c.get(f"{API}/palettes/{pal['id']}/summary").json()
        assert summ["n"] == 1 and summ["pending"] == 0 and summ["worst_de"] is None


@pytest.mark.slow
def test_whole_demo_library_is_summarised_after_activation(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    url = _seed(tmp_path_factory, None)
    with _client(url, auto=True) as c:
        t0 = time.monotonic()
        c.post(f"{API}/models/cmykw-demo@1/activate")
        lib = _wait_all(c, timeout=120)
        assert len(lib) == 20, len(lib)
        print(f"20 library matches in {time.monotonic() - t0:.1f} s")
        pal = c.post(
            f"{API}/palettes", json={"name": "All", "color_ids": [e["id"] for e in lib]}
        ).json()
        summ = c.get(f"{API}/palettes/{pal['id']}/summary").json()
        assert summ["pending"] == 0 and summ["n"] == 20
        assert summ["within"] + summ["uncertain"] + summ["out"] == 20
        assert summ["worst_de"] == max(e["match"]["de"] for e in lib)


def test_failed_solves_are_not_retried_until_inputs_change(
    small: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def broken(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise RuntimeError("solver blew up")

    monkeypatch.setattr(matches, "solve", broken)
    with _client(small, auto=False) as c:

        def settle() -> None:
            deadline = time.monotonic() + 30
            while (t := c.app.state.match_task) is not None and not t.done():  # type: ignore[attr-defined]
                assert time.monotonic() < deadline
                time.sleep(0.05)

        c.get(f"{API}/colors", params={"with_match": True})
        time.sleep(0.2)
        settle()
        assert len(calls) == 3 and len(c.app.state.match_failed) == 3  # type: ignore[attr-defined]
        for _ in range(3):  # asking again does not solve them again
            assert all(
                e["match"] is None
                for e in c.get(f"{API}/colors", params={"with_match": True}).json()
            )
            time.sleep(0.1)
            settle()
        assert len(calls) == 3
        # a changed colour is tried again
        cid = c.get(f"{API}/colors").json()[0]["id"]
        c.patch(f"{API}/colors/{cid}", json={"lab": [50, 5, 5]})
        c.get(f"{API}/colors", params={"with_match": True})
        time.sleep(0.2)
        settle()
        assert len(calls) == 4
