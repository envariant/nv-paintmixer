"""Live events: the hub (resume, reset, slow clients) and GET /events (server-sent events)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from paintmixer.api import events
from paintmixer.api.app import create_app
from paintmixer.api.routers import events as events_router
from paintmixer.config import Settings
from paintmixer.demo import seed_demo
from tests.api_helpers import dispense

API = "/api/v1"
Ev = dict[str, Any]


def read_events(
    c: TestClient,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    stop: Callable[[Ev], bool] | None = None,
    stop_at_keepalive: bool = False,
) -> list[Ev]:
    """Events (``{"event", "data", "id"}``) until ``stop`` says so, a keep-alive comment (when
    asked) or the server closes the stream (``limit``)."""
    out: list[Ev] = []
    cur: Ev = {}
    with c.stream("GET", f"{API}/events", params=params, headers=headers) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith(":"):
                if stop_at_keepalive:
                    break
                continue
            if line == "":
                if "event" in cur:
                    out.append(cur)
                    if stop is not None and stop(cur):
                        break
                cur = {}
                continue
            key, _, value = line.partition(": ")
            cur[key] = json.loads(value) if key == "data" else value
    return out


# --- the hub ---------------------------------------------------------------------------------


def test_hub_resume_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "BUFFER", 3)
    hub = events.EventHub()
    ids = [hub.publish("job", {"n": i}).id for i in range(5)]  # buffer keeps the last 3
    assert ids[-1] == hub.last_id and ids[0] == f"{hub.boot}:1"
    _s, backlog, reset = hub.subscribe(None)
    assert backlog == [] and not reset
    _s, backlog, reset = hub.subscribe(ids[1])  # events 3..5 are still buffered
    assert [e.data["n"] for e in backlog] == [2, 3, 4] and not reset
    _s, backlog, reset = hub.subscribe(ids[4])  # up to date
    assert backlog == [] and not reset
    for stale in (ids[0], "other-boot:3", f"{hub.boot}:99", "garbage"):
        _s, backlog, reset = hub.subscribe(stale)
        assert reset and backlog == [], stale


def test_slow_client_overflows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "QUEUE", 2)

    async def run() -> events.Subscriber:
        hub = events.EventHub()
        hub.loop = asyncio.get_running_loop()
        sub, _b, _r = hub.subscribe(None)
        for i in range(3):
            hub.publish("job", {"n": i})
        await asyncio.sleep(0.05)  # deliveries run on the loop
        return sub

    sub = asyncio.run(run())
    assert sub.overflow and sub.queue.qsize() == 2


# --- the stream ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def c(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path_factory.mktemp('events') / 'db.sqlite'}"
    seed_demo(url)
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as client:
        yield client


@pytest.fixture(autouse=True)
def _quick_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_router, "KEEPALIVE_S", 0.2)


def _job(c: TestClient) -> int:
    sol = c.post(f"{API}/solve", json={"target": {"lab": [60, -10, 15]}, "top_n": 1}).json()
    comps = {x["paint_id"]: x["fraction"] for x in sol["candidates"][0]["components"]}
    r = c.post(
        f"{API}/jobs", json={"name": "Sage", "target": {"lab": [60, -10, 15]}, "components": comps}
    )
    return int(r.json()["id"])


def test_connect_sends_hello_and_a_machine_snapshot(c: TestClient) -> None:
    evs = read_events(c, params={"limit": 1})
    assert [e["event"] for e in evs] == ["hello", "machine"]
    hello = evs[0]["data"]
    assert hello["types"] == sorted(events.TYPES) and hello["last_event_id"].startswith(
        hello["boot"]
    )
    assert evs[1]["data"]["label"] == "Machine ready" and "id" not in evs[1]  # snapshot: no id


def test_missed_job_events_are_replayed(c: TestClient) -> None:
    mark = read_events(c, params={"limit": 1, "types": "machine"})[0]["data"]["last_event_id"]
    job_id = _job(c)
    dispense(c, job_id)  # runs while nobody listens
    evs = read_events(
        c,
        params={"types": "job", "job_id": job_id},
        headers={"Last-Event-ID": mark},
        stop_at_keepalive=True,  # the backlog is replayed before any keep-alive
    )
    jobs = [e for e in evs if e["event"] == "job"]
    assert all(e["data"]["id"] == job_id for e in jobs)
    statuses = [e["data"]["status"] for e in jobs]
    assert statuses[0] == "draft" and "queued" in statuses and "pouring" in statuses
    assert "measuring" in statuses and statuses[-1] in ("done", "measured")
    assert jobs[-1]["data"]["running"] is False and jobs[-1]["data"]["progress"] == 1.0
    seqs = [int(e["id"].split(":")[1]) for e in jobs]
    assert seqs == sorted(seqs)


def test_live_events_while_a_job_runs(c: TestClient) -> None:
    job_id = _job(c)
    got: list[Ev] = []

    def listen() -> None:
        got.extend(
            read_events(
                c,
                params={"types": "job,machine"},
                stop=lambda e: (
                    e["event"] == "job"
                    and e["data"]["id"] == job_id
                    and not e["data"]["running"]
                    and e["data"]["status"] != "draft"
                ),
            )
        )

    t = threading.Thread(target=listen)
    t.start()
    time.sleep(0.3)  # connected
    c.post(f"{API}/jobs/{job_id}/dispense", json={})
    t.join(30)
    assert not t.is_alive()
    machine = [e["data"] for e in got if e["event"] == "machine"]
    assert machine[0]["label"] == "Machine ready"  # the connect snapshot
    assert any(m["state"] == "pouring" for m in machine)
    assert got[-1]["data"]["running"] is False
    deadline = time.monotonic() + 2  # the server notices the closed stream at its next write
    while c.app.state.events.n_subscribers and time.monotonic() < deadline:  # type: ignore[attr-defined]
        time.sleep(0.05)
    assert c.app.state.events.n_subscribers == 0  # type: ignore[attr-defined]


def test_unknown_resume_id_asks_for_a_reset(c: TestClient) -> None:
    # a resuming client gets no connect snapshot: stop at the reset
    evs = read_events(c, headers={"Last-Event-ID": "x:1"}, stop=lambda e: e["event"] == "reset")
    assert [e["event"] for e in evs] == ["hello", "reset"]
    assert c.get(f"{API}/events", params={"types": "job,nope"}).json()["error"]["code"] == (
        "unknown_event_type"
    )


def test_model_and_library_match_events(tmp_path_factory: pytest.TempPathFactory) -> None:
    url = f"sqlite:///{tmp_path_factory.mktemp('ev-lib') / 'db.sqlite'}"
    seed_demo(url)
    settings = Settings(database_url=url, compute_workers=0, match_cache_auto=True)
    with TestClient(create_app(settings)) as c:
        for e in c.get(f"{API}/colors").json()[1:]:  # one colour keeps it quick
            c.delete(f"{API}/colors/{e['id']}")
        got: list[Ev] = []

        def listen() -> None:
            got.extend(
                read_events(
                    c,
                    params={"types": "model,match,matches"},
                    stop=lambda e: e["event"] == "matches" and e["data"]["state"] == "idle",
                )
            )

        t = threading.Thread(target=listen)
        t.start()
        time.sleep(0.3)
        c.post(f"{API}/models/cmykw-demo@2/activate")
        t.join(60)
        assert not t.is_alive()
    kinds = [(e["event"], e["data"].get("event") or e["data"].get("state")) for e in got[1:]]
    assert kinds[0] == ("model", "activated") and got[1]["data"]["model"]["ref"] == "cmykw-demo@2"
    assert ("matches", "refreshing") in kinds and kinds[-1] == ("matches", "idle")
    (match,) = [e["data"] for e in got if e["event"] == "match"]
    assert match["match"]["model_version"] == 2
