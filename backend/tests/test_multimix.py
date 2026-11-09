from __future__ import annotations

from math import comb

import numpy as np
import pytest
from fastapi.testclient import TestClient

from paintmixer.calibration.synthetic import STARTER_IDS, synthetic_paints
from paintmixer.colorsci import KMModel
from paintmixer.solver.multimix import (
    MAX_CELLS,
    MultimixError,
    grid_parts,
    lattice_size,
    multimix,
    polygon_layout,
    simplex_lattice,
)

API = "/api/v1"


def _model() -> KMModel:
    ps = synthetic_paints(STARTER_IDS)
    return KMModel(np.stack([p.K for p in ps]), np.stack([p.S for p in ps]))


@pytest.mark.parametrize(("k", "d"), [(2, 4), (3, 10), (4, 6), (6, 10)])
def test_simplex_lattice_is_complete_and_ordered(k: int, d: int) -> None:
    parts = simplex_lattice(k, d)
    assert parts.shape == (comb(d + k - 1, k - 1), k) == (lattice_size(k, d), k)
    assert np.all(parts.sum(axis=1) == d) and parts.min() >= 0
    assert len({tuple(r) for r in parts}) == len(parts)  # no duplicates
    assert parts[0].tolist() == [d] + [0] * (k - 1)  # pure first paint first
    assert parts[-1].tolist() == [0] * (k - 1) + [d]
    # lexicographic, first paint descending
    assert [tuple(-x for x in r) for r in parts] == sorted(tuple(-x for x in r) for r in parts)


def test_interior_lattice_and_limits() -> None:
    inner = simplex_lattice(3, 6, interior=True)
    assert inner.min() >= 1 and len(inner) == comb(5, 2) == lattice_size(3, 6, True)
    assert simplex_lattice(6, 10).shape == (3003, 6)
    with pytest.raises(MultimixError, match="limit"):
        simplex_lattice(6, 20)  # 53130 cells
    with pytest.raises(MultimixError):
        simplex_lattice(7, 2)
    with pytest.raises(MultimixError):
        simplex_lattice(4, 3, interior=True)


def test_grid_parts_is_an_nd_array() -> None:
    shape, parts = grid_parts([[0, 2, 4, 8], [0, 1], [0, 1, 2]])
    assert shape == (4, 2, 3) and parts.shape == (24, 3)
    assert parts[0].tolist() == [0, 0, 0] and parts[1].tolist() == [0, 0, 1]  # last axis fastest
    assert parts.reshape(4, 2, 3, 3)[3, 1, 2].tolist() == [8, 1, 2]
    with pytest.raises(MultimixError):
        grid_parts([[0, 1]] * 7)
    with pytest.raises(MultimixError):
        grid_parts([[0, -1], [1]])
    with pytest.raises(MultimixError, match="limit"):
        grid_parts([list(range(11))] * 4)  # 14641 cells


def test_polygon_layout() -> None:
    v = polygon_layout(np.eye(3))
    np.testing.assert_allclose(v[0], [0, 1], atol=1e-12)  # first paint on top
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1)
    np.testing.assert_allclose(polygon_layout(np.full((1, 6), 1 / 6)), [[0, 0]], atol=1e-12)
    np.testing.assert_allclose(polygon_layout(np.eye(2)), [[-1, 0], [1, 0]], atol=1e-12)


def test_multimix_predictions_match_the_model() -> None:
    m = _model()
    idx = [0, 2, 4]  # white, phthalo blue, arylide yellow
    parts = simplex_lattice(3, 4)
    cells = multimix(m, idx, parts)
    assert len(cells) == 15
    c = np.zeros(5)
    c[idx] = parts[5] / 4
    np.testing.assert_allclose(cells[5].reflectance, m.reflectance(c))  # type: ignore[arg-type]
    pure_blue = next(x for x in cells if x.parts == (0.0, 4.0, 0.0))
    np.testing.assert_allclose(pure_blue.reflectance, m.reflectance(np.eye(5)[2]))  # type: ignore[arg-type]
    # the empty cell of a grid is kept so the array shape survives
    _, gp = grid_parts([[0, 1], [0, 1], [0, 1]])
    g = multimix(m, idx, gp)
    assert g[0].fractions is None and g[0].hex is None and all(x.hex for x in g[1:])
    assert g[2].fractions == (0.0, 1.0, 0.0) and g[3].fractions == (0.0, 0.5, 0.5)
    # proportional cells (1:1 and 2:2) are the same mixture
    _, gp2 = grid_parts([[0, 2], [0, 2], [0, 2]])
    assert multimix(m, idx, gp2)[3].hex == g[3].hex


def test_multimix_api(fitted_client: TestClient) -> None:
    c = fitted_client
    six = list(STARTER_IDS)  # the starter model has 5 paints
    r = c.post(f"{API}/multimix", json={"paint_ids": six, "divisions": 4})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["mode"] == "simplex" and res["n_cells"] == comb(8, 4) == res["shape"][0]
    assert len(res["vertices"]) == 5 and res["cells"][0]["spectrum"] is None
    assert all(cell["hex"].startswith("#") for cell in res["cells"])
    grid = c.post(
        f"{API}/multimix",
        json={
            "paint_ids": ["titanium-white", "phthalo-blue", "arylide-yellow"],
            "mode": "grid",
            "levels": [[0, 4, 8], [0, 1], [0, 1, 2]],
            "include_spectra": True,
        },
    ).json()
    assert grid["shape"] == [3, 2, 3] and grid["n_cells"] == 18
    assert grid["cells"][0]["hex"] is None and grid["cells"][0]["fractions"] is None
    cell = grid["cells"][17]
    assert cell["index"] == [2, 1, 2] and cell["parts"] == [8, 1, 2] and len(cell["spectrum"]) == 36
    assert sum(cell["fractions"]) == pytest.approx(1)
    bad = c.post(f"{API}/multimix", json={"paint_ids": six, "divisions": 60})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_multimix"
    assert str(MAX_CELLS) in bad.json()["error"]["message"]
    r = c.post(f"{API}/multimix", json={"paint_ids": ["phthalo-blue", "phthalo-blue"]})
    assert r.status_code == 422
    r = c.post(
        f"{API}/multimix", json={"paint_ids": ["phthalo-blue", "arylide-yellow"], "mode": "grid"}
    )
    assert r.status_code == 422
    r = c.post(f"{API}/multimix", json={"paint_ids": ["phthalo-blue", "pyrrole-red"]})
    assert r.json()["error"]["code"] == "uncalibrated_paint"
