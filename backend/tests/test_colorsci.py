import warnings
from pathlib import Path

import numpy as np
import pytest

from paintmixer.colorsci import (
    WAVELENGTHS,
    Illuminant,
    delta_e_2000,
    hex_to_srgb,
    lab_to_srgb,
    lab_to_xyz,
    reflectance_to_lab,
    reflectance_to_srgb,
    reflectance_to_xyz,
    resample,
    srgb_to_hex,
    srgb_to_lab,
    white_point,
    xyz_to_lab,
)
from paintmixer.colorsci.recovery import lab_to_reflectance

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import colour

DATA = Path(__file__).parent / "data"


def _sharma() -> np.ndarray:
    return np.loadtxt(DATA / "sharma2005_ciede2000.csv", delimiter=",", skiprows=2)


def test_grid() -> None:
    assert WAVELENGTHS.size == 31
    assert WAVELENGTHS[0] == 400 and WAVELENGTHS[-1] == 700


def test_de2000_sharma_all_pairs() -> None:
    d = _sharma()
    assert d.shape == (34, 8)
    de = delta_e_2000(d[:, 1:4], d[:, 4:7])
    np.testing.assert_allclose(de, d[:, 7], atol=1e-4)


def test_de2000_symmetric_and_zero() -> None:
    d = _sharma()
    np.testing.assert_allclose(
        delta_e_2000(d[:, 1:4], d[:, 4:7]), delta_e_2000(d[:, 4:7], d[:, 1:4]), atol=1e-4
    )
    np.testing.assert_allclose(delta_e_2000(d[:, 1:4], d[:, 1:4]), 0.0, atol=1e-12)


def test_de2000_matches_colour_science_random() -> None:
    rng = np.random.default_rng(0)
    lab1 = rng.uniform([0, -100, -100], [100, 100, 100], size=(2000, 3))
    lab2 = lab1 + rng.normal(0, 8, size=lab1.shape)
    ours = delta_e_2000(lab1, lab2)
    theirs = colour.delta_E(lab1, lab2, method="CIE 2000")
    # identical except possibly at exact 180-degree hue ties (measure-zero for random data)
    np.testing.assert_allclose(ours, theirs, atol=1e-8)


def test_white_points_match_cie() -> None:
    expected = {
        Illuminant.D65: [95.047, 100.0, 108.883],
        Illuminant.D50: [96.422, 100.0, 82.521],
        Illuminant.A: [109.850, 100.0, 35.585],
        Illuminant.F11: [100.962, 100.0, 64.350],
    }
    for ill, xyz in expected.items():
        np.testing.assert_allclose(white_point(ill), xyz, atol=0.1)


def test_reflectance_to_xyz_matches_colour_integration() -> None:
    sd = colour.SDS_COLOURCHECKERS["ColorChecker N Ohta"]["dark skin"]
    r = np.array([sd[w] for w in WAVELENGTHS])
    ours = reflectance_to_xyz(r)
    ref = colour.sd_to_XYZ(sd, illuminant=colour.SDS_ILLUMINANTS["D65"], method="Integration")
    np.testing.assert_allclose(ours, ref, atol=0.1)


def test_perfect_reflector_is_white() -> None:
    lab = reflectance_to_lab(np.ones(31))
    np.testing.assert_allclose(lab, [100, 0, 0], atol=1e-9)
    srgb = reflectance_to_srgb(np.ones(31))
    np.testing.assert_allclose(srgb.rgb, [1, 1, 1], atol=1e-6)
    assert not srgb.out_of_gamut
    for ill in Illuminant:
        np.testing.assert_allclose(reflectance_to_lab(np.ones(31), ill), [100, 0, 0], atol=1e-9)


def test_lab_xyz_round_trip() -> None:
    rng = np.random.default_rng(1)
    lab = rng.uniform([0, -80, -80], [100, 80, 80], size=(500, 3))
    np.testing.assert_allclose(xyz_to_lab(lab_to_xyz(lab)), lab, atol=1e-9)


def test_known_lab_values() -> None:
    # sRGB primaries (Lindbloom, D65): red = (53.2408, 80.0925, 67.2032)
    np.testing.assert_allclose(srgb_to_lab([1, 0, 0]), [53.2408, 80.0925, 67.2032], atol=1e-3)
    np.testing.assert_allclose(srgb_to_lab([0, 0, 1]), [32.2970, 79.1875, -107.8602], atol=1e-3)
    np.testing.assert_allclose(srgb_to_lab([1, 1, 1]), [100, 0, 0], atol=1e-6)
    ref = colour.XYZ_to_Lab(colour.sRGB_to_XYZ([0.2, 0.5, 0.7]))
    np.testing.assert_allclose(srgb_to_lab([0.2, 0.5, 0.7]), ref, atol=0.01)


def test_srgb_round_trip_and_gamut_flag() -> None:
    rng = np.random.default_rng(2)
    rgb = rng.uniform(0, 1, size=(300, 3))
    back = lab_to_srgb(srgb_to_lab(rgb))
    np.testing.assert_allclose(back.rgb, rgb, atol=1e-6)
    assert not back.out_of_gamut.any()
    vivid = lab_to_srgb([50, 0, -120])
    assert bool(vivid.out_of_gamut)
    assert np.all((vivid.rgb >= 0) & (vivid.rgb <= 1))


def test_hex() -> None:
    np.testing.assert_allclose(hex_to_srgb("#ff8000"), [1, 128 / 255, 0])
    assert srgb_to_hex(hex_to_srgb("#1a2B3c")) == "#1a2b3c"
    assert srgb_to_hex(hex_to_srgb("abc")) == "#aabbcc"
    with pytest.raises(ValueError):
        hex_to_srgb("#12345")


def test_resample_colormunki_grid() -> None:
    wl = np.arange(380, 731, 10)
    values = (wl - 380) / 1000.0
    out = resample(wl, values)
    np.testing.assert_allclose(out, (WAVELENGTHS - 380) / 1000.0)
    wl5 = np.arange(380, 731, 5)
    out5 = resample(wl5, np.sin(wl5 / 50.0))
    np.testing.assert_allclose(out5, np.sin(WAVELENGTHS / 50.0), atol=1e-12)
    with pytest.raises(ValueError):
        resample(np.arange(450, 701, 10), np.zeros(26))


def test_recovery_reproduces_lab() -> None:
    for lab in ([50, 40, 30], [80, -10, 20], [30, 5, -40], [95, 0, 2]):
        r = lab_to_reflectance(lab)
        assert r.shape == (31,)
        assert np.all((r > 0) & (r <= 1))
        assert delta_e_2000(reflectance_to_lab(r), lab) < 0.5
