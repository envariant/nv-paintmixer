import numpy as np

from paintmixer.colorsci import KMModel
from paintmixer.colorsci.km import (
    dr_inf_dks,
    dsaunderson_dr,
    inverse_saunderson,
    ks_from_r,
    mix_ks,
    r_inf,
    r_layer,
    saunderson,
)


def test_r_inf_ks_round_trip() -> None:
    r = np.linspace(0.01, 0.99, 99)
    np.testing.assert_allclose(r_inf(ks_from_r(r)), r, atol=1e-12)
    assert r_inf(0.0) == 1.0


def test_saunderson_round_trip() -> None:
    r = np.linspace(0.0, 1.0, 101)
    for k1, k2 in [(0.0, 0.5), (0.04, 0.6), (0.0, 0.0)]:
        np.testing.assert_allclose(inverse_saunderson(saunderson(r, k1, k2), k1, k2), r, atol=1e-12)
    # k1 = k2 = 0 is the identity
    np.testing.assert_allclose(saunderson(r, 0.0, 0.0), r)
    # perfect internal white stays white when k1 = 0
    assert np.isclose(saunderson(1.0, 0.0, 0.5), 1.0)


def test_derivatives_match_finite_differences() -> None:
    ks = np.linspace(0.01, 20, 50)
    h = 1e-6
    np.testing.assert_allclose(dr_inf_dks(ks), (r_inf(ks + h) - r_inf(ks - h)) / (2 * h), rtol=1e-5)
    r = np.linspace(0.05, 0.95, 20)
    num = (saunderson(r + h) - saunderson(r - h)) / (2 * h)
    np.testing.assert_allclose(dsaunderson_dr(r), num, rtol=1e-6)


def test_mixing_is_scale_invariant() -> None:
    rng = np.random.default_rng(0)
    k = rng.uniform(0.01, 3, size=(4, 31))
    s = rng.uniform(0.1, 2, size=(4, 31))
    c = rng.dirichlet(np.ones(4), size=10)
    alpha = rng.uniform(0.5, 2, size=31)  # per-band scale ambiguity
    np.testing.assert_allclose(mix_ks(c, k, s), mix_ks(c, k * alpha, s * alpha))
    # concentrations need not be normalised
    np.testing.assert_allclose(mix_ks(c, k, s), mix_ks(3 * c, k, s))


def test_single_paint_mixture_equals_masstone() -> None:
    k = np.full((2, 31), 0.2)
    s = np.ones((2, 31))
    m = KMModel(k, s)
    np.testing.assert_allclose(m.reflectance([1.0, 0.0]), saunderson(r_inf(0.2)))


def test_finite_layer_limits() -> None:
    ks = np.array([0.05, 0.5, 5.0])
    rg_white, rg_black = 0.9, 0.02
    thick = r_layer(ks, 1e4, rg_white)
    np.testing.assert_allclose(thick, r_inf(ks), atol=1e-10)
    np.testing.assert_allclose(r_layer(ks, 1e4, rg_black), r_inf(ks), atol=1e-10)
    # zero thickness shows the substrate
    np.testing.assert_allclose(r_layer(ks, 0.0, rg_white), rg_white, atol=1e-9)
    # over black a thin layer is darker than opaque, over white it is lighter (for low K/S)
    assert np.all(r_layer(ks, 0.5, rg_black) < r_inf(ks))
    assert r_layer(0.05, 0.5, rg_white) > r_inf(0.05)
    # monotone approach to R_inf over black
    sx = np.linspace(0.01, 50, 200)
    vals = r_layer(0.1, sx, rg_black)
    assert np.all(np.diff(vals) >= 0) and np.all(np.diff(vals[:50]) > 0)


def test_finite_layer_k_zero_limit() -> None:
    # pure scatterer: R = (R_g + SX (1 - R_g)) / (1 + SX (1 - R_g))
    sx = np.array([0.1, 1.0, 10.0])
    rg = 0.2
    expected = (rg + sx * (1 - rg)) / (1 + sx * (1 - rg))
    np.testing.assert_allclose(r_layer(0.0, sx, rg), expected, rtol=1e-6)


def test_model_layer_vs_opaque() -> None:
    rng = np.random.default_rng(3)
    k = rng.uniform(0.01, 3, size=(3, 31))
    s = rng.uniform(0.5, 2, size=(3, 31))
    m = KMModel(k, s, k1=0.0, k2=0.5)
    c = np.array([[0.2, 0.3, 0.5], [1.0, 0.0, 0.0]])
    sub = np.full(31, 0.85)
    np.testing.assert_allclose(m.reflectance_layer(c, 1e5, sub), m.reflectance(c), atol=1e-9)
    assert m.reflectance(c).shape == (2, 31)
