from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from paintmixer.calibration.synthetic import STARTER_IDS, synthetic_paints
from paintmixer.colorsci import KMModel, reflectance_to_lab
from paintmixer.domain import PaintInfo
from paintmixer.solver.ramp import ramp, ramp_fractions
from paintmixer.worksheet.plan import plan_worksheet
from paintmixer.worksheet.preview import preview_plan
from tests.api_helpers import import_paints

API = "/api/v1"


def _model() -> KMModel:
    ps = synthetic_paints(STARTER_IDS)
    return KMModel(np.stack([p.K for p in ps]), np.stack([p.S for p in ps]))


def test_ramp_fractions() -> None:
    np.testing.assert_allclose(ramp_fractions(5), [1, 0.75, 0.5, 0.25, 0])
    log = ramp_fractions(5, "log", 0.01)
    np.testing.assert_allclose(log, [1, 10**-0.5, 0.1, 10**-1.5, 0.01])
    assert np.allclose(log[1:] / log[:-1], log[1] / log[0])  # constant dilution factor
    with pytest.raises(ValueError):
        ramp_fractions(1)
    with pytest.raises(ValueError):
        ramp_fractions(4, "log", 0)


def test_tint_ladder_gets_lighter_and_ends_on_the_paints() -> None:
    m = _model()
    steps = ramp(m, 2, 0, ramp_fractions(8, "log", 0.01))  # phthalo blue into white
    L = [s.lab[0] for s in steps]
    assert np.all(np.diff(L) > 0)
    np.testing.assert_allclose(steps[0].reflectance, m.reflectance(np.eye(5)[2]))
    lin = ramp(m, 2, 4, ramp_fractions(3))  # blue -> yellow
    np.testing.assert_allclose(lin[-1].reflectance, m.reflectance(np.eye(5)[4]))
    assert lin[1].lab[1] < -10  # the middle of blue + yellow is green (a* < 0)


def test_linear_ramp_is_a_two_paint_simplex() -> None:
    from paintmixer.solver.multimix import multimix, simplex_lattice

    m = _model()
    steps = ramp(m, 2, 4, ramp_fractions(7))  # phthalo blue -> arylide yellow, 7 steps
    cells = multimix(m, [2, 4], simplex_lattice(2, 6))
    assert [s.hex for s in steps] == [c.hex for c in cells]
    for s_, c in zip(steps, cells, strict=True):
        np.testing.assert_allclose(s_.reflectance, c.reflectance)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ramp(m, 2, 2, [0.5])
    with pytest.raises(ValueError):
        ramp(m, 2, 4, [1.5])


def test_worksheet_preview_matches_layer_model(paints: dict[str, PaintInfo]) -> None:
    from paintmixer.calibration.synthetic import substrate_black, substrate_white, true_tau

    plan = plan_worksheet([paints[p] for p in STARTER_IDS])
    m = _model()
    prev = preview_plan(
        plan, m, list(STARTER_IDS), true_tau(), substrate_white(), substrate_black()
    )
    assert len(prev) == plan.n_rows
    # carbon black is opaque at the standard gap: both halves of the chart look the same
    w, b = prev["MT-carbon-black-W"].lab, prev["MT-carbon-black-B"].lab
    assert abs(w[0] - b[0]) < 1.0
    sw = reflectance_to_lab(substrate_white())
    assert prev["SUB-W"].lab == pytest.approx(tuple(sw), abs=1e-6)
    # thin white over black is darker than over white
    assert prev["MT-titanium-white-75-B"].lab[0] < prev["MT-titanium-white-75-W"].lab[0]
    partial = preview_plan(
        plan,
        m.subset([0, 1]),
        ["titanium-white", "carbon-black"],
        true_tau(),
        substrate_white(),
        substrate_black(),
    )
    assert "TN-carbon-black-10-W" in partial and "TN-phthalo-blue-5-W" not in partial


def test_ramp_and_worksheet_preview_api(fitted_client: TestClient) -> None:
    c = fitted_client
    r = c.post(f"{API}/ramp", json={"paint_a": "phthalo-blue", "steps": 6, "scale": "log"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["paint_b"] == "titanium-white" and len(res["steps"]) == 6
    assert res["steps"][0]["fraction_a"] == 1 and len(res["steps"][0]["spectrum"]) == 36
    assert res["steps"][-1]["lab"][0] > res["steps"][0]["lab"][0]
    r = c.post(f"{API}/ramp", json={"paint_a": "phthalo-blue", "paint_b": "phthalo-blue"})
    assert r.json()["error"]["code"] == "same_paint"
    r = c.post(f"{API}/ramp", json={"paint_a": "pyrrole-red"})
    assert r.json()["error"]["code"] == "uncalibrated_paint"
    ws = c.post(f"{API}/worksheet", json={"paint_ids": list(STARTER_IDS)}).json()
    assert ws["preview_model_version"] >= 1 and ws["preview_model_source"] == "calibration"
    assert all(row["predicted_hex"] for row in ws["rows"])
    ws9 = c.post(f"{API}/worksheet", json={}).json()  # includes uncalibrated paints
    rows = {row["sample_id"]: row for row in ws9["rows"]}
    assert rows["TN-pyrrole-red-5-W"]["predicted_hex"] is None
    assert rows["TN-phthalo-blue-5-W"]["predicted_hex"]


def test_worksheet_without_model_has_no_preview(client: TestClient) -> None:
    import_paints(client)
    ws = client.post(f"{API}/worksheet", json={"paint_ids": list(STARTER_IDS)}).json()
    assert ws["preview_model_version"] is None
    assert all(row["predicted_hex"] is None for row in ws["rows"])
