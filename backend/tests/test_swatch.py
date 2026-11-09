from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from paintmixer.calibration.swatch import SwatchError, SwatchPaint, model_from_swatches
from paintmixer.calibration.synthetic import STARTER_IDS, swatch_hexes, synthetic_paints
from paintmixer.colorsci import KMModel, delta_e_2000, reflectance_to_lab
from paintmixer.colorsci.convert import hex_to_srgb, srgb_to_lab
from paintmixer.domain import PaintRole
from tests.api_helpers import import_paints

API = "/api/v1"


def _swatches(with_tint: bool) -> tuple[list[SwatchPaint], KMModel]:
    ps = synthetic_paints(STARTER_IDS)
    true = KMModel(np.stack([p.K for p in ps]), np.stack([p.S for p in ps]))
    hexes = swatch_hexes(ps)
    out = []
    for p in ps:
        mass, tint = hexes[p.info.id]
        tint_lab = srgb_to_lab(hex_to_srgb(tint)) if (tint and with_tint) else None
        out.append(
            SwatchPaint(p.info.id, p.info.role, srgb_to_lab(hex_to_srgb(mass)), tint_lab, 0.1)
        )
    return out, true


def _mixture_errors(est: KMModel, true: KMModel, n: int = 300) -> np.ndarray:
    rng = np.random.default_rng(0)
    des = []
    for _ in range(n):
        k = int(rng.integers(2, 5))
        c = np.zeros(true.n_paints)
        c[rng.choice(true.n_paints, k, replace=False)] = rng.dirichlet(np.ones(k))
        des.append(
            float(
                delta_e_2000(
                    reflectance_to_lab(est.reflectance(c)), reflectance_to_lab(true.reflectance(c))
                )
            )
        )
    return np.array(des)


def test_masstones_are_reproduced() -> None:
    sw, _ = _swatches(with_tint=True)
    m = model_from_swatches(sw)
    est = KMModel(m.K, m.S, m.k1, m.k2)
    for i, s in enumerate(sw):
        lab = reflectance_to_lab(est.reflectance(np.eye(len(sw))[i]))
        assert float(delta_e_2000(lab, s.masstone_lab)) < 1.0, s.paint_id
    assert m.paint_ids[0] == "titanium-white" and np.all(m.S[0] == 1)
    assert m.K.shape == (5, 36)


def test_tint_swatches_improve_accuracy_and_recover_scattering() -> None:
    sw_t, true = _swatches(with_tint=True)
    sw_m, _ = _swatches(with_tint=False)
    with_tint = model_from_swatches(sw_t)
    mass_only = model_from_swatches(sw_m)
    e_t = _mixture_errors(KMModel(with_tint.K, with_tint.S), true)
    e_m = _mixture_errors(KMModel(mass_only.K, mass_only.S), true)
    # rough by design, but a tint swatch clearly helps
    assert np.median(e_t) < np.median(e_m) and np.percentile(e_t, 90) < np.percentile(e_m, 90)
    assert np.median(e_t) < 5.0
    assert with_tint.scattering_source["carbon-black"] == "tint"
    assert mass_only.scattering_source["carbon-black"] == "assumed"
    s_black = with_tint.S[with_tint.paint_ids.index("carbon-black"), 0]
    assert s_black == pytest.approx(0.30, rel=0.2)  # truth: 0.30
    # black's tint is reproduced well; for chromatics the reconstructed spectrum limits the
    # match, which is reported per paint
    assert with_tint.tint_match_de["carbon-black"] < 1.0
    assert set(with_tint.tint_match_de) == set(STARTER_IDS[1:])
    assert any("reproduces its tint swatch only to" in w for w in with_tint.warnings)
    assert any("no tint swatch" in w for w in mass_only.warnings)
    assert "expect several dE2000" in with_tint.warnings[0]


def test_requires_white() -> None:
    sw, _ = _swatches(with_tint=False)
    with pytest.raises(SwatchError):
        model_from_swatches([s for s in sw if s.role != PaintRole.WHITE])


def test_swatch_model_api(client: TestClient) -> None:
    import_paints(client)
    r = client.post(f"{API}/models/from-swatches", json={"paint_ids": list(STARTER_IDS)})
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["model"]["source"] == "swatches" and res["model"]["active"]
    assert res["scattering_source"]["titanium-white"] == "white"
    assert res["scattering_source"]["phthalo-blue"] == "tint"
    health = client.get(f"{API}/health").json()
    assert health["active_model_source"] == "swatches"
    sol = client.post(f"{API}/solve", json={"target": {"lab": [60, -10, -20]}}).json()
    assert sol["model_source"] == "swatches"
    assert "swatch colours" in sol["warnings"][0] and sol["candidates"]
    pred = client.post(
        f"{API}/predict", json={"components": {"titanium-white": 0.9, "phthalo-blue": 0.1}}
    ).json()
    assert pred["model_source"] == "swatches"
    # default selection: every active paint with a swatch (all 9 sample paints)
    r = client.post(f"{API}/models/from-swatches", json={"activate": False})
    assert r.status_code == 201 and len(r.json()["model"]["paint_ids"]) == 9
    assert not r.json()["model"]["active"]
    # a paint without a swatch is refused
    client.patch(f"{API}/paints/pyrrole-red", json={"swatch_hex": None})
    r = client.post(
        f"{API}/models/from-swatches", json={"paint_ids": ["titanium-white", "pyrrole-red"]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "missing_swatch"
    assert (
        client.patch(f"{API}/paints/pyrrole-red", json={"swatch_hex": "not-a-hex"}).status_code
        == 422
    )
    r = client.post(f"{API}/models/from-swatches", json={"paint_ids": ["phthalo-blue"]})
    assert r.json()["error"]["code"] == "swatch_model_failed"  # no white
    models = client.get(f"{API}/models").json()
    assert {x["source"] for x in models} == {"swatches"}
