from __future__ import annotations

import numpy as np
import pytest

from paintmixer.colorsci import Illuminant, delta_e_2000, reflectance_to_lab
from paintmixer.domain import PaintRole
from paintmixer.solver.gamut import compute_gamut
from paintmixer.solver.refine import Weights
from paintmixer.solver.solve import SolveOptions, Target, pool_warnings, predict, solve
from tests.solver_helpers import pool_model, random_recipe_targets

FAST = SolveOptions(gamut_check=False)


def test_lab_jacobian_matches_finite_differences() -> None:
    m = pool_model(9)
    rng = np.random.default_rng(0)
    idx = np.array([rng.choice(9, 4, replace=False) for _ in range(6)])
    c = rng.dirichlet(np.ones(4), size=6)
    lab, jac = m.lab_jac(idx, c)
    np.testing.assert_allclose(lab, m.lab(idx, c))
    h = 1e-6
    for j in range(4):
        e = np.zeros(4)
        e[j] = h
        num = (m.lab(idx, c + e) - m.lab(idx, c - e)) / (2 * h)
        np.testing.assert_allclose(jac[:, :, j], num, rtol=1e-4, atol=1e-5)


def test_known_recipes_starter5() -> None:
    m = pool_model(5)
    for lab, _idx, _c in random_recipe_targets(m, 10, seed=11):
        res = solve(m, Target(lab=lab), FAST)
        assert res.candidates[0].de2000 < 0.5, (lab, res.candidates[0])


def test_result_structure_and_quantisation() -> None:
    m = pool_model(5)
    lab = np.array([62.0, 18.0, 25.0])
    opts = SolveOptions(batch_volume_ml=50.0, resolution_ml=0.1, top_n=4)
    res = solve(m, Target(lab=lab), opts)
    assert 1 <= len(res.candidates) <= 4
    assert [c.rank for c in res.candidates] == list(range(1, len(res.candidates) + 1))
    objs = [c.objective for c in res.candidates]
    assert objs == sorted(objs)
    for c in res.candidates:
        v = np.array(c.volumes_ml)
        np.testing.assert_allclose(v / 0.1, np.round(v / 0.1), atol=1e-9)
        assert np.all(v >= 0.05 - 1e-12)  # min dose
        assert abs(v.sum() - 50.0) <= 0.1 * len(v) + 1e-9
        assert abs(sum(c.fractions_quantised) - 1) < 1e-9
        assert len(c.predicted_spectrum) == 31
        assert set(c.metamerism) == {"A", "F11"}
        assert c.cost == pytest.approx(c.cost_per_ml * v.sum())
        assert c.predicted_hex.startswith("#")
        assert min(c.fractions) >= opts.min_fraction - 1e-9
        assert c.de2000 >= 0 and c.dose_sensitivity >= 0
    assert res.reference_spectrum_source == "reconstructed"
    assert res.in_gamut is True
    assert res.search == "exhaustive" and res.n_subsets == 31


def test_deterministic() -> None:
    m = pool_model(9)
    lab = np.array([45.0, -20.0, 10.0])
    a = solve(m, Target(lab=lab), FAST)
    b = solve(m, Target(lab=lab), FAST)
    assert [c.paint_ids for c in a.candidates] == [c.paint_ids for c in b.candidates]
    assert [c.fractions for c in a.candidates] == [c.fractions for c in b.candidates]


def test_spectral_target_and_metamerism() -> None:
    m = pool_model(9)
    idx = np.array([0, 3, 4])
    R = m.reflectance(idx[None], np.array([[0.5, 0.3, 0.2]]))[0]
    res = solve(m, Target(lab=reflectance_to_lab(R), spectrum=R), FAST)
    best = res.candidates[0]
    assert res.reference_spectrum_source == "measured"
    assert best.de2000 < 0.3
    # a spectral match should be nearly free of metamerism
    assert max(best.metamerism.values()) < 0.5
    # matching under illuminant A uses the spectrum's Lab under A
    res_a = solve(
        m,
        Target(lab=reflectance_to_lab(R), spectrum=R),
        SolveOptions(gamut_check=False, illuminant=Illuminant.A),
    )
    assert res_a.target_lab == pytest.approx(list(reflectance_to_lab(R, Illuminant.A)))


def test_out_of_gamut_returns_nearest_with_warning() -> None:
    m = pool_model(5)
    res = solve(m, Target(lab=np.array([60.0, 90.0, -90.0])), SolveOptions())
    assert res.in_gamut is False
    assert res.candidates and res.nearest_de > 1.0
    assert any("Out of gamut" in w for w in res.warnings)
    assert any("nearest achievable" in w for w in res.candidates[0].warnings)


def test_include_white_constraint() -> None:
    m = pool_model(5)
    lab = np.array([55.0, 5.0, 40.0])
    white = "titanium-white"
    req = solve(m, Target(lab=lab), SolveOptions(gamut_check=False, include_white=True))
    assert all(white in c.paint_ids for c in req.candidates)
    exc = solve(m, Target(lab=lab), SolveOptions(gamut_check=False, include_white=False))
    assert all(white not in c.paint_ids for c in exc.candidates)


def test_max_paints_and_min_fraction() -> None:
    m = pool_model(9)
    lab = np.array([50.0, 10.0, -10.0])
    res = solve(
        m, Target(lab=lab), SolveOptions(gamut_check=False, max_paints=3, min_fraction=0.05)
    )
    for c in res.candidates:
        assert len(c.paint_ids) <= 3
        assert min(c.fractions) >= 0.05 - 1e-9


def test_black_helps_neutrals_and_darks() -> None:
    """Including black lowers dE or dose sensitivity vs a CMYW-only pool."""
    with_k = pool_model(5)
    cmyw = pool_model(
        ids=["titanium-white", "phthalo-blue", "quinacridone-magenta", "arylide-yellow"]
    )
    targets = [
        np.array([20.0, 0.0, 0.0]),  # dark neutral
        np.array([50.0, 0.0, 0.0]),  # mid grey
        np.array([12.0, 2.0, -4.0]),  # near black
        np.array([30.0, 8.0, 10.0]),  # dark brown
    ]
    for lab in targets:
        a = solve(with_k, Target(lab=lab), FAST).candidates[0]
        b = solve(cmyw, Target(lab=lab), FAST).candidates[0]
        better_de = a.de2000 < b.de2000 - 0.05
        better_sens = a.de2000 <= b.de2000 + 0.05 and a.dose_sensitivity < b.dose_sensitivity
        assert better_de or better_sens, (
            lab,
            a.de2000,
            b.de2000,
            a.dose_sensitivity,
            b.dose_sensitivity,
        )


def test_weights_change_choice() -> None:
    m = pool_model(9)
    lab = np.array([60.0, 20.0, 30.0])
    base = solve(m, Target(lab=lab), SolveOptions(gamut_check=False, weights=Weights(n_paints=0.0)))
    few = solve(m, Target(lab=lab), SolveOptions(gamut_check=False, weights=Weights(n_paints=1.0)))
    assert len(few.candidates[0].paint_ids) <= len(base.candidates[0].paint_ids)
    assert few.candidates[0].de2000 < 3.0
    default = solve(m, Target(lab=lab), FAST)
    cheap = solve(m, Target(lab=lab), SolveOptions(gamut_check=False, weights=Weights(cost=20.0)))
    assert cheap.candidates[0].cost_per_ml <= default.candidates[0].cost_per_ml + 1e-9


def test_gamut() -> None:
    m = pool_model(5)
    g = compute_gamut(m)
    assert g.slices and g.L_min < 15 and g.L_max > 90
    assert all(s.chroma.shape == (36,) for s in g.slices)
    for lab, _i, _c in random_recipe_targets(m, 30, seed=3):
        assert g.contains(lab, margin=3.0)
    assert not g.contains(np.array([60.0, 90.0, -90.0]))
    assert not g.contains(np.array([99.9, 0.0, 60.0]))


def test_pool_warnings() -> None:
    cmy = pool_model(ids=["phthalo-blue", "quinacridone-magenta"])
    w = " ".join(pool_warnings(cmy))
    assert "No white" in w and "No black" in w and "Fewer than 3 chromatic" in w
    assert pool_warnings(pool_model(5)) == []


def test_predict_matches_model() -> None:
    m = pool_model(5)
    r = predict(m, ["titanium-white", "phthalo-blue"], [3, 1])
    np.testing.assert_allclose(r, m.reflectance(np.array([[0, 2]]), np.array([[0.75, 0.25]]))[0])
    assert m.role_mask(PaintRole.WHITE).sum() == 1
    assert float(delta_e_2000(reflectance_to_lab(r), reflectance_to_lab(r))) == 0.0


def test_staged_mode_runs_on_small_pool() -> None:
    m = pool_model(12)
    lab, _idx, _c = random_recipe_targets(m, 1, seed=8)[0]
    res = solve(m, Target(lab=lab), SolveOptions(gamut_check=False, search="staged"))
    assert res.search == "staged"
    assert res.candidates[0].de2000 < 0.5
