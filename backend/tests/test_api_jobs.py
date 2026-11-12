from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api_helpers import dispense

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
        j = dispense(c, job["id"], simulate=True, measure=False)
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
    assert len([e for e in final["corrections"] if "result" in e]) == len(des)
    rounds = [e for e in final["corrections"] if e.get("kind") == "round"]
    assert [r["de"] for r in rounds] == [round(d, 4) for d in des]
    assert [r["label"] for r in rounds][:2] == ["First pour", "Fix 1"]
    cups = [sum(e["actual_ml"] for e in ev["results"]) for ev in final["dispensed"]["events"]]
    assert len(cups) == len(des) and all(v >= 0 for v in cups)
    assert any(x["id"] == job["id"] for x in c.get(f"{API}/jobs", params={"status": "done"}).json())


def test_job_measured_lab_and_cap(fitted_client: TestClient) -> None:
    c = fitted_client
    job = _job(c, [50.0, 10.0, 10.0])
    dispense(c, job["id"], measure=False)
    j = c.post(f"{API}/jobs/{job['id']}/measurement", json={"lab": [55.0, 10.0, 10.0]}).json()
    assert 3 < j["measured"]["de_to_target"] < 6 and j["measured"]["simulated"] is False
    j = c.post(
        f"{API}/jobs/{job['id']}/correct", json={"max_iterations": 1, "mode": "remix"}
    ).json()
    fixes = [e for e in j["corrections"] if "result" in e]
    assert j["status"] == "correcting" and fixes[0]["mode"] == "remix"
    dispense(c, job["id"], measure=False)
    c.post(f"{API}/jobs/{job['id']}/measurement", json={"lab": [55.0, 10.0, 10.0]})
    j = c.post(f"{API}/jobs/{job['id']}/correct", json={"max_iterations": 1}).json()
    assert j["status"] == "needs_attention"
    assert c.post(f"{API}/jobs/{job['id']}/dispense", json={}).status_code == 409
    assert c.post(f"{API}/jobs/{job['id']}/measurement", json={}).status_code == 422
    assert c.get(f"{API}/jobs/99999").status_code == 404


def test_export_csv(fitted_client: TestClient) -> None:
    import csv
    import io

    c = fitted_client
    measured = _job(c, [55.0, -5.0, 10.0])
    dispense(c, measured["id"], simulate=True)
    resp = c.post(
        f"{API}/jobs",
        json={
            "name": "=HYPERLINK(1)",  # a spreadsheet must not run it
            "target": {"lab": [50.0, 0.0, 0.0]},
            "components": {"titanium-white": 0.5, "carbon-black": 0.5},
        },
    )
    assert resp.status_code == 201, resp.text
    draft = resp.json()
    r = c.get(f"{API}/jobs/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert list(rows[0]) == [
        "id", "name", "created", "status", "rounds", "final_de", "poured_ml", "paints"
    ]  # fmt: skip
    by_id = {int(row["id"]): row for row in rows}
    assert [int(row["id"]) for row in rows] == sorted(by_id, reverse=True)  # newest first
    d = by_id[draft["id"]]
    assert d["name"] == "'=HYPERLINK(1)" and d["status"] == "draft"
    assert d["rounds"] == "0" and d["final_de"] == "" and d["poured_ml"] == "0.0"
    assert d["paints"] == "White (Titanium); Black (Carbon)"
    assert d["created"].endswith("+00:00")
    job = c.get(f"{API}/jobs/{measured['id']}").json()
    row = by_id[measured["id"]]
    rounds = [e for e in job["corrections"] if e.get("kind") == "round"]
    assert int(row["rounds"]) == len(rounds) >= 1
    assert float(row["final_de"]) == round(job["measured"]["de_to_target"], 2)
    assert float(row["poured_ml"]) == round(sum(job["dispensed"]["cup_ml"].values()), 1)
    only = c.get(f"{API}/jobs/export.csv", params={"status": "draft"}).text
    assert {row["status"] for row in csv.DictReader(io.StringIO(only))} == {"draft"}
