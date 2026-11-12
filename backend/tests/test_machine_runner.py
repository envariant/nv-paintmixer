"""Jobs run on the machine in the background: rounds, auto-correction, pause / resume / cancel,
the real-dispenser path over TCP, and recovery after a restart."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from paintmixer.api.app import create_app
from paintmixer.config import Settings
from paintmixer.db import models as m
from paintmixer.db.session import get_engine, migrate
from paintmixer.demo import seed_demo
from paintmixer.hardware.firmware_sim import SimulatedFirmware
from tests.api_helpers import dispense, wait_job
from tests.hardware_helpers import firmware_over_tcp

API = "/api/v1"
LAB = [62.0, -8.0, -22.0]


@pytest.fixture(scope="module")
def c(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path_factory.mktemp('run') / 'db.sqlite'}"
    seed_demo(url)
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as client:
        yield client


def _job(c: TestClient, name: str = "Harbour Fog") -> dict[str, Any]:
    sol = c.post(f"{API}/solve", json={"target": {"lab": LAB}, "top_n": 1}).json()
    comps = {x["paint_id"]: x["fraction"] for x in sol["candidates"][0]["components"]}
    r = c.post(
        f"{API}/jobs",
        json={"name": name, "target": {"lab": LAB}, "components": comps, "batch_volume_ml": 100},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def _rounds(j: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in j["corrections"] if e.get("kind") == "round"]


def _until(c: TestClient, job_id: int, pred: Any, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        j: dict[str, Any] = c.get(f"{API}/jobs/{job_id}").json()
        if pred(j):
            return j
        assert time.monotonic() < deadline, (j["status"], j["step"])
        time.sleep(0.01)


def test_run_pours_measures_and_records_the_round(c: TestClient) -> None:
    job = _job(c)
    r = c.post(f"{API}/jobs/{job['id']}/dispense", json={})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["step"] == "Queued"
    j = wait_job(c, job["id"])
    assert j["status"] in ("done", "measured") and j["progress"] == 1.0
    (first,) = _rounds(j)
    assert first["label"] == "First pour" and first["hex"].startswith("#")
    assert first["de"] == pytest.approx(j["measured"]["de_to_target"], abs=1e-4)
    assert 95 < first["added_ml"] < 105 and first["poured_ml"] == pytest.approx(first["added_ml"])
    assert j["dispensed"]["dispenser"] == "DSP-01-sim"


def test_auto_correction_rounds_until_within_tolerance(c: TestClient) -> None:
    c.patch(f"{API}/settings", json={"accept_tolerance_de": 0.6})
    try:
        job = _job(c)
        # the simulated paint is 8 % lighter than the model thinks: the first pour misses
        j = dispense(c, job["id"], auto_correct_rounds=5, simulate_gain=1.08, seed=3)
    finally:
        c.patch(f"{API}/settings", json={"accept_tolerance_de": 1.0})
    rounds = _rounds(j)
    assert j["status"] == "done", (j["status"], [r["de"] for r in rounds])
    assert [r["label"] for r in rounds] == ["First pour"] + [
        f"Fix {i}" for i in range(1, len(rounds))
    ]
    assert len(rounds) >= 2 and rounds[0]["de"] > 0.6 >= rounds[-1]["de"]
    assert all(0 < r["added_ml"] < rounds[0]["added_ml"] for r in rounds[1:])  # "Fix 1 · +2.7 ml"
    assert "Within tolerance" in j["step"]


def test_without_auto_correction_it_waits_for_a_decision(c: TestClient) -> None:
    job = _job(c)
    j = dispense(c, job["id"], simulate_gain=1.08, seed=3)
    assert j["status"] == "measured" and "accept or correct again" in j["step"]
    # Correct again = POST /correct, then pour it
    assert c.post(f"{API}/jobs/{job['id']}/correct", json={}).json()["status"] == "correcting"
    j = dispense(c, job["id"], simulate_gain=1.08, seed=4)
    assert [r["label"] for r in _rounds(j)] == ["First pour", "Fix 1"]
    if j["status"] == "measured":
        assert c.post(f"{API}/jobs/{job['id']}/accept").json()["status"] == "accepted"


def test_pause_and_resume_between_channels(c: TestClient) -> None:
    job = _job(c, "Plum Mist")
    c.post(f"{API}/jobs/{job['id']}/dispense", json={"simulate_ml_per_s": 200})
    assert c.post(f"{API}/jobs/{job['id']}/pause").json()["paused"] is True
    j = _until(c, job["id"], lambda j: j["step"] == "Paused")
    assert j["status"] == "pouring" and j["paused"]
    st = c.get(f"{API}/machine").json()
    assert st["label"] == "Paused · Plum Mist" and st["current_job"]["paused"]
    progress = j["progress"]
    time.sleep(0.4)
    assert c.get(f"{API}/jobs/{job['id']}").json()["progress"] == progress  # nothing poured
    assert c.post(f"{API}/jobs/{job['id']}/resume").json()["paused"] is False
    j = wait_job(c, job["id"])
    assert j["status"] in ("done", "measured") and not j["paused"]
    assert c.post(f"{API}/jobs/{job['id']}/pause").status_code == 409  # not on the machine


def test_cancel_stops_between_channels_and_keeps_the_pour(c: TestClient) -> None:
    job = _job(c)
    c.post(f"{API}/jobs/{job['id']}/dispense", json={"simulate_ml_per_s": 100})
    _until(c, job["id"], lambda j: j["status"] == "pouring" and j["progress"] > 0)
    st = c.get(f"{API}/machine").json()
    assert st["state"] == "pouring" and 0 < st["current_job"]["progress"] < 1
    c.post(f"{API}/jobs/{job['id']}/cancel", json={"reason": "wrong cup"})
    j = wait_job(c, job["id"])
    last = j["corrections"][-1]
    assert j["status"] == "cancelled" and last["result"] == "cancelled"
    assert last["reason"] == "wrong cup" and 0 < last["poured_ml"] < 95
    assert sum(j["dispensed"]["cup_ml"].values()) == pytest.approx(last["poured_ml"])


def test_cancel_a_queued_job_at_once(c: TestClient) -> None:
    a, b = _job(c, "A"), _job(c, "B")
    c.post(f"{API}/jobs/{a['id']}/dispense", json={"simulate_ml_per_s": 100})
    c.post(f"{API}/jobs/{b['id']}/dispense", json={})
    assert c.get(f"{API}/jobs/{b['id']}").json()["status"] == "queued"  # one job at a time
    out = c.post(f"{API}/jobs/{b['id']}/cancel", json={}).json()
    assert out["status"] == "cancelled" and out["dispensed"] is None
    c.post(f"{API}/jobs/{a['id']}/cancel", json={})
    assert wait_job(c, a["id"])["status"] == "cancelled"


def test_real_dispenser_over_tcp(c: TestClient) -> None:
    assert (
        c.post(f"{API}/jobs/{_job(c)['id']}/dispense", json={"simulate": False}).json()["error"][
            "code"
        ]
        == "no_dispenser"
    )
    fw = SimulatedFirmware(name="DSP-01")
    with firmware_over_tcp(fw) as port:
        c.patch(
            f"{API}/settings",
            json={"dispenser_transport": "tcp", "dispenser_address": f"127.0.0.1:{port}"},
        )
        try:
            assert c.get(f"{API}/machine").json()["transport"] == "tcp"
            job = _job(c)
            j = dispense(c, job["id"], simulate=False)
            # no inline instrument: it waits for a measurement
            assert j["status"] == "dispensed" and j["step"] == "Waiting for a measurement"
            assert j["dispensed"]["dispenser"] == "DSP-01" and len(fw.dispenser.log) >= 2
            j = c.post(f"{API}/jobs/{job['id']}/measurement", json={"lab": LAB}).json()
            assert _rounds(j)[0]["label"] == "First pour"
            # a reservoir runs dry: the job needs attention, what was poured is kept
            fw.empty_channels = {max(ch for ch, _r, _a in fw.dispenser.log)}
            j = dispense(c, _job(c)["id"], simulate=False)
            assert j["status"] == "needs_attention" and "EMPTY" in j["step"]
        finally:
            c.patch(
                f"{API}/settings", json={"dispenser_transport": "none", "dispenser_address": ""}
            )


def test_jobs_interrupted_by_a_restart_need_attention(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    url = f"sqlite:///{tmp_path_factory.mktemp('restart') / 'db.sqlite'}"
    migrate(url)
    with Session(get_engine(url)) as s:
        for status in ("pouring", "measured"):
            s.add(m.Job(name=status, status=status, step="Pouring", recipe={"iteration": 0}))
        s.add(m.Job(name="between rounds", status="correcting", running=True, recipe={}))
        s.commit()
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as client:
        jobs = {j["name"]: j for j in client.get(f"{API}/jobs").json()}
    assert (
        jobs["pouring"]["status"] == "needs_attention" and "Interrupted" in jobs["pouring"]["step"]
    )
    assert jobs["between rounds"]["status"] == "needs_attention"
    assert not any(j["running"] for j in jobs.values())
    assert jobs["measured"]["status"] == "measured"  # not on the machine: left alone
