from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api_helpers import fit, import_paints, upload_calibration
from tests.helpers import SAMPLE_DATA

API = "/api/v1"


def err(r) -> str:  # type: ignore[no-untyped-def]
    body = r.json()
    assert set(body) == {"error"} and {"code", "message", "details"} <= set(body["error"])
    return str(body["error"]["code"])


# --- system / settings ----------------------------------------------------------------------


def test_health_and_openapi(client: TestClient) -> None:
    r = client.get(f"{API}/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["active_model_version"] is None
    spec = client.get(f"{API}/openapi.json").json()
    paths = set(spec["paths"])
    for p in [
        "/api/v1/solve",
        "/api/v1/predict",
        "/api/v1/gamut",
        "/api/v1/paints",
        "/api/v1/calibration/fit",
        "/api/v1/worksheet",
        "/api/v1/models/{version}/activate",
    ]:
        assert p in paths


def test_settings_roundtrip(client: TestClient) -> None:
    s = client.get(f"{API}/settings").json()
    assert s["currency"] == "SGD" and s["max_paints"] == 5
    r = client.patch(f"{API}/settings", json={"batch_volume_ml": 250, "weights": {"cost": 2.0}})
    assert r.status_code == 200
    assert r.json()["batch_volume_ml"] == 250 and r.json()["weights"]["cost"] == 2.0
    assert client.get(f"{API}/settings").json()["batch_volume_ml"] == 250
    r = client.patch(f"{API}/settings", json={"max_paints": 0})
    assert r.status_code == 422 and err(r) == "validation_error"


def test_not_found_envelope(client: TestClient) -> None:
    r = client.get(f"{API}/paints/nope")
    assert r.status_code == 404 and err(r) == "not_found"
    r = client.get(f"{API}/does-not-exist")
    assert r.status_code == 404 and err(r) == "not_found"


# --- paints ---------------------------------------------------------------------------------


def test_paint_crud_and_loaded_rules(client: TestClient) -> None:
    body = {"id": "test-white", "name": "Test White", "role": "white", "density_g_per_ml": 1.4}
    r = client.post(f"{API}/paints", json=body)
    assert r.status_code == 201 and r.json()["loaded"] is False and r.json()["calibrated"] is False
    assert client.post(f"{API}/paints", json=body).status_code == 409
    assert client.post(f"{API}/paints", json={**body, "id": "Bad Id"}).status_code == 422
    # loaded requires a channel; channels must be unique among loaded paints
    r = client.patch(f"{API}/paints/test-white", json={"loaded": True})
    assert r.status_code == 422 and err(r) == "channel_required"
    assert (
        client.patch(
            f"{API}/paints/test-white", json={"loaded": True, "dispenser_channel": 1}
        ).status_code
        == 200
    )
    client.post(f"{API}/paints", json={"id": "test-blue", "name": "Blue"})
    r = client.patch(f"{API}/paints/test-blue", json={"loaded": True, "dispenser_channel": 1})
    assert r.status_code == 409 and err(r) == "conflict"
    r = client.patch(f"{API}/paints/test-blue", json={"loaded": True, "dispenser_channel": 99})
    assert err(r) == "channel_out_of_range"
    # diluted stock
    r = client.post(
        f"{API}/paints",
        json={"id": "blue-10", "name": "Blue 10%", "parent_paint_id": "test-blue", "dilution": 0.1},
    )
    assert r.status_code == 201 and r.json()["dilution"] == 0.1
    r = client.post(
        f"{API}/paints", json={"id": "blue-x", "name": "x", "parent_paint_id": "test-blue"}
    )
    assert err(r) == "bad_dilution"
    assert client.delete(f"{API}/paints/test-blue").status_code == 409  # parent of a stock
    loaded = client.get(f"{API}/paints", params={"loaded": True}).json()
    assert [p["id"] for p in loaded] == ["test-white"]
    assert client.delete(f"{API}/paints/blue-10").status_code == 204
    assert client.delete(f"{API}/paints/test-blue").status_code == 204


def test_paint_import(client: TestClient) -> None:
    out = import_paints(client)
    assert len(out["created"]) == 9 and not out["errors"]
    again = import_paints(client)
    assert len(again["updated"]) == 9 and not again["created"]
    loaded = client.get(f"{API}/paints", params={"loaded": True}).json()
    assert len(loaded) == 5 and sorted(p["dispenser_channel"] for p in loaded) == [1, 2, 3, 4, 5]


# --- colour library -------------------------------------------------------------------------


def test_color_library(client: TestClient) -> None:
    r = client.post(f"{API}/colors", json={"name": "Teal", "source": "test", "hex": "#1f7a7a"})
    assert r.status_code == 201
    c = r.json()
    assert c["hex"] == "#1f7a7a" and len(c["lab"]) == 3 and c["in_srgb_gamut"]
    r = client.post(f"{API}/colors", json={"name": "Teal", "source": "test", "hex": "#000"})
    assert r.status_code == 409
    r = client.post(f"{API}/colors", json={"name": "Nothing", "source": "test"})
    assert r.status_code == 422
    r = client.post(f"{API}/colors", json={"name": "Bad", "hex": "#zzz"})
    assert err(r) == "bad_colour"
    r = client.patch(f"{API}/colors/{c['id']}", json={"lab": [50, 0, 0]})
    assert r.json()["lab"] == [50, 0, 0]
    with (SAMPLE_DATA / "color_library.csv").open("rb") as fh:
        r = client.post(f"{API}/colors/import", files={"file": ("lib.csv", fh, "text/csv")})
    assert r.status_code == 200 and r.json()["created"] == 20 and not r.json()["errors"]
    found = client.get(f"{API}/colors", params={"q": "grey"}).json()
    assert {x["name"] for x in found} >= {"Mid Grey 50", "Light Grey 80"}
    green = next(x for x in client.get(f"{API}/colors").json() if x["name"] == "Laser Green")
    assert green["in_srgb_gamut"] is False
    assert client.delete(f"{API}/colors/{c['id']}").status_code == 204
    assert client.get(f"{API}/colors/{c['id']}").status_code == 404


# --- worksheet ------------------------------------------------------------------------------


def test_worksheet_json_csv_html(client: TestClient) -> None:
    import_paints(client)
    ids = [
        "titanium-white",
        "carbon-black",
        "phthalo-blue",
        "quinacridone-magenta",
        "arylide-yellow",
    ]
    body = {"paint_ids": ids, "options": {"batch_g": 10, "scale_resolution_g": 0.01}}
    r = client.post(f"{API}/worksheet", json=body)
    assert r.status_code == 200, r.text
    ws = r.json()
    assert ws["n_rows"] == len(ws["rows"]) == 124 and ws["n_holdout"] > 0
    assert set(ws["totals_g"]) == set(ids)
    assert any(lm["paint_id"] == "carbon-black" for lm in ws["low_mass"])
    csv = client.post(f"{API}/worksheet/csv", json=body)
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith(
        "sample_id,type,substrate,components,notes,components_mass_g,r380"
    )
    assert len(csv.text.splitlines()) == 125
    html = client.post(f"{API}/worksheet/html", json=body)
    assert "Actual g" in html.text
    r = client.post(f"{API}/worksheet", json={"paint_ids": ["nope"]})
    assert err(r) == "unknown_paint"


# --- calibration + models -------------------------------------------------------------------


def test_validate_and_upload_errors(client: TestClient) -> None:
    import_paints(client)
    bad = (
        "sample_id,type,substrate,components,notes,"
        + ",".join(f"r{w}" for w in range(400, 701, 10))
        + "\n"
    )
    bad += "MX-1-W,mixture,white,phthalo-blue:0.5;nope:0.5,," + ",".join(["0.5"] * 30) + ",abc\n"
    r = client.post(
        f"{API}/calibration/validate", files={"file": ("bad.csv", bad.encode(), "text/csv")}
    )
    rep = r.json()
    assert r.status_code == 200 and rep["ok"] is False
    issues = {(i["row"], i["column"], i["code"]) for i in rep["issues"]}
    assert (2, "components", "unknown_paint") in issues and (2, "r700", "not_numeric") in issues
    r = client.post(
        f"{API}/calibration/upload", files={"file": ("bad.csv", bad.encode(), "text/csv")}
    )
    assert r.json()["stored"] == 0
    r = client.post(f"{API}/calibration/fit", json={})
    assert r.status_code == 422 and err(r) == "no_samples"
    r = client.post(f"{API}/solve", json={"target": {"lab": [50, 0, 0]}})
    assert r.status_code == 409 and err(r) == "no_active_model"


def test_upload_fit_activate(client: TestClient) -> None:
    import_paints(client)
    up = upload_calibration(client)
    assert up["stored"] == 124 and up["report"]["ok"] and up["replaced"] == 0
    assert upload_calibration(client)["replaced"] == 124
    samples = client.get(
        f"{API}/calibration/samples", params={"paint_id": "phthalo-blue", "type": "tint"}
    ).json()
    assert len(samples) == 8 and samples[0]["hex"].startswith("#")
    run = fit(client)
    assert run["status"] == "succeeded" and run["model_version"] == 1 and run["progress"] == 1.0
    run2 = fit(client, activate=False, k2=0.55)
    assert run2["model_version"] == 2
    models = client.get(f"{API}/models").json()
    assert [(x["version"], x["active"]) for x in models] == [(2, False), (1, True)]
    detail = client.get(f"{API}/models/1").json()
    assert detail["holdout"]["method"] == "flagged" and detail["holdout"]["n_samples"] > 0
    assert len(detail["residuals"]) == 122
    assert client.post(f"{API}/models/2/activate").json()["active"] is True
    assert client.get(f"{API}/health").json()["active_model_version"] == 2
    assert client.get(f"{API}/models/active").json()["k2"] == 0.55
    spectra = client.get(f"{API}/models/1/spectra").json()
    assert len(spectra["wavelengths"]) == 36 and len(spectra["paints"]) == 5
    assert spectra["paints"][0]["S"] == [1.0] * 36
    paints = {p["id"]: p for p in client.get(f"{API}/paints").json()}
    assert paints["phthalo-blue"]["calibrated"] and not paints["pyrrole-red"]["calibrated"]
    # deleting a paint used by samples is refused
    assert client.delete(f"{API}/paints/phthalo-blue").status_code == 409


# --- mixing ---------------------------------------------------------------------------------


def test_solve_variants(fitted_client: TestClient) -> None:
    c = fitted_client
    r = c.post(f"{API}/solve", json={"target": {"lab": [55, -10, -25]}, "top_n": 3})
    assert r.status_code == 200, r.text
    res = r.json()
    assert sorted(res["pool"]) == sorted(
        ["titanium-white", "carbon-black", "phthalo-blue", "quinacridone-magenta", "arylide-yellow"]
    )
    assert 1 <= len(res["candidates"]) <= 3
    best = res["candidates"][0]
    assert best["de2000"] < 1.0 and best["currency"] == "SGD"
    assert abs(sum(x["fraction"] for x in best["components"]) - 1) < 1e-9
    assert abs(sum(x["volume_ml"] for x in best["components"]) - res["batch_volume_ml"]) < 1
    assert res["reference_spectrum_source"] == "reconstructed"
    for target in ({"hex": "#6f4e37"}, {"srgb": [0.2, 0.5, 0.4]}):
        assert c.post(f"{API}/solve", json={"target": target}).status_code == 200
    # spectrum target and library target
    spec = c.post(
        f"{API}/predict", json={"components": {"titanium-white": 0.7, "phthalo-blue": 0.3}}
    ).json()["spectrum"]
    r = c.post(f"{API}/solve", json={"target": {"spectrum": spec}, "illuminant": "A"})
    assert r.json()["reference_spectrum_source"] == "measured" and r.json()["illuminant"] == "A"
    assert r.json()["candidates"][0]["de2000"] < 0.5
    lib = c.post(f"{API}/colors", json={"name": "Lib Grey", "lab": [60, 0, 0]}).json()
    r = c.post(f"{API}/solve", json={"target": {"library_id": lib["id"]}})
    assert r.json()["target_name"] == "Lib Grey"
    # validation of target and pool
    assert (
        c.post(f"{API}/solve", json={"target": {"lab": [50, 0, 0], "hex": "#fff"}}).status_code
        == 422
    )
    r = c.post(f"{API}/solve", json={"target": {"lab": [50, 0, 0]}, "pool": ["pyrrole-red"]})
    assert r.status_code == 422 and err(r) == "uncalibrated_paint"
    r = c.post(
        f"{API}/solve", json={"target": {"lab": [50, 0, 0]}, "max_paints": 5, "min_fraction": 0.3}
    )
    assert err(r) == "bad_constraints"


def test_solve_out_of_gamut_and_warnings(fitted_client: TestClient) -> None:
    r = fitted_client.post(f"{API}/solve", json={"target": {"lab": [40, 60, -80]}})
    res = r.json()
    assert res["in_gamut"] is False and res["nearest_de"] > 1
    assert any("Out of gamut" in w for w in res["warnings"])
    r = fitted_client.post(
        f"{API}/solve",
        json={"target": {"lab": [50, 0, 0]}, "pool": ["phthalo-blue", "arylide-yellow"]},
    )
    w = " ".join(r.json()["warnings"])
    assert "No white" in w and "No black" in w


def test_predict_and_gamut(fitted_client: TestClient) -> None:
    r = fitted_client.post(f"{API}/predict", json={"components": {"titanium-white": 1}})
    p = r.json()
    assert r.status_code == 200 and p["lab"]["D65"][0] > 90 and set(p["lab"]) == {"D65", "A", "F11"}
    r = fitted_client.post(f"{API}/predict", json={"components": {"titanium-white": -1}})
    assert err(r) == "bad_components"
    g = fitted_client.get(f"{API}/gamut").json()
    assert g["L_min"] < 20 and g["L_max"] > 90 and len(g["slices"][0]["a"]) == 36
    g2 = fitted_client.get(f"{API}/gamut", params={"pool": "titanium-white,phthalo-blue"}).json()
    assert g2["pool"] == ["titanium-white", "phthalo-blue"]


def test_committed_openapi_is_current() -> None:
    import json
    from pathlib import Path

    from paintmixer.api.app import create_app

    committed = json.loads((Path(__file__).parents[1] / "openapi.json").read_text())
    assert committed == json.loads(json.dumps(create_app().openapi())), "run `make gen-api`"


def test_process_pool_compute(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Solve and fit through real worker processes (the production configuration)."""
    from paintmixer.api.app import create_app
    from paintmixer.config import Settings

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", compute_workers=1))
    with TestClient(app) as c:
        import_paints(c)
        upload_calibration(c)
        run = fit(c)
        assert run["status"] == "succeeded", run
        r = c.post(f"{API}/solve", json={"target": {"lab": [60, 0, 0]}})
        assert r.status_code == 200 and r.json()["candidates"]
        assert c.get(f"{API}/gamut").status_code == 200
