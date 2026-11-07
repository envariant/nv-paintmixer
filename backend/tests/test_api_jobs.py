from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def _job(c: TestClient, lab: list[float]) -> dict:  # type: ignore[type-arg]
    sol = c.post(f"{API}/solve", json={"target": {"lab": lab, "name": "Test"}}).json()
    best = sol["candidates"][0]
    comps = {x["paint_id"]: x["fraction"] for x in best["components"]}
    r = c.post(
        f"{API}/jobs",
        json={"target": {"lab": lab, "name": "Test"}, "components": comps, "batch_volume_ml": 100},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_job_closed_loop_with_simulators(fitted_client: TestClient) -> None:
    c = fitted_client
    job = _job(c, [62.0, -8.0, -22.0])
    assert job["status"] == "draft" and job["model_version"] >= 1
    assert abs(sum(job["recipe"]["volumes_ml"]) - 100) < 1
    # measure before dispensing is refused
    r = c.post(f"{API}/jobs/{job['id']}/measurement", json={"simulate": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "bad_state"
    statuses: list[str] = []
    des: list[float] = []
    for _ in range(7):
        j = c.post(f"{API}/jobs/{job['id']}/dispense", json={"simulate": True}).json()
        assert j["status"] == "dispensed"
        # simulated instrument: the real paint is 8 % lighter than the model thinks
        j = c.post(
            f"{API}/jobs/{job['id']}/measurement",
            json={"simulate": True, "simulate_gain": 1.08, "seed": len(des)},
        ).json()
        des.append(j["measured"]["de_to_target"])
        j = c.post(f"{API}/jobs/{job['id']}/correct", json={"tolerance_de": 0.6}).json()
        statuses.append(j["status"])
        if j["status"] != "correcting":
            break
    assert statuses[-1] == "done", (statuses, des)
    assert des[0] > 1.0 and des[-1] <= 0.6
    final = c.get(f"{API}/jobs/{job['id']}").json()
    assert len(final["corrections"]) == len(des)
    cups = [sum(e["actual_ml"] for e in ev["results"]) for ev in final["dispensed"]["events"]]
    assert len(cups) == len(des) and all(v >= 0 for v in cups)
    assert any(x["id"] == job["id"] for x in c.get(f"{API}/jobs", params={"status": "done"}).json())


def test_job_measured_lab_and_cap(fitted_client: TestClient) -> None:
    c = fitted_client
    job = _job(c, [50.0, 10.0, 10.0])
    c.post(f"{API}/jobs/{job['id']}/dispense", json={})
    j = c.post(f"{API}/jobs/{job['id']}/measurement", json={"lab": [55.0, 10.0, 10.0]}).json()
    assert 3 < j["measured"]["de_to_target"] < 6 and j["measured"]["simulated"] is False
    j = c.post(
        f"{API}/jobs/{job['id']}/correct", json={"max_iterations": 1, "mode": "remix"}
    ).json()
    assert j["status"] == "correcting" and j["corrections"][0]["mode"] == "remix"
    c.post(f"{API}/jobs/{job['id']}/dispense", json={})
    c.post(f"{API}/jobs/{job['id']}/measurement", json={"lab": [55.0, 10.0, 10.0]})
    j = c.post(f"{API}/jobs/{job['id']}/correct", json={"max_iterations": 1}).json()
    assert j["status"] == "needs_attention"
    assert c.post(f"{API}/jobs/{job['id']}/dispense", json={}).status_code == 409
    assert c.post(f"{API}/jobs/{job['id']}/measurement", json={}).status_code == 422
    assert c.get(f"{API}/jobs/99999").status_code == 404
