from __future__ import annotations

import warnings

import numpy as np
import pytest

from paintmixer.colorsci import lab_to_srgb, reflectance_to_srgb, srgb_to_lab
from paintmixer.colorsci.convert import _M_XYZ_TO_RGB, _srgb_decode
from paintmixer.colorsci.oklab import (
    JND,
    delta_e_ok,
    gamut_map_lrgb,
    in_gamut,
    lrgb_to_oklab,
    oklab_to_lrgb,
    oklab_to_oklch,
    oklch_to_oklab,
)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import colour


def test_ottosson_reference_values() -> None:
    # Ottosson (2020) table: XYZ (D65) -> OKLab
    table = [
        ([0.950, 1.000, 1.089], [1.000, 0.000, 0.000]),
        ([1.000, 0.000, 0.000], [0.450, 1.236, -0.019]),
        ([0.000, 1.000, 0.000], [0.922, -0.671, 0.263]),
        ([0.000, 0.000, 1.000], [0.153, -1.415, -0.449]),
    ]
    for xyz, lab in table:
        got = lrgb_to_oklab(np.array(xyz) @ _M_XYZ_TO_RGB.T)
        np.testing.assert_allclose(got, lab, atol=2e-3)


def test_matches_colour_science_and_round_trips() -> None:
    rng = np.random.default_rng(0)
    lrgb = rng.uniform(0, 1, size=(500, 3))
    xyz = colour.RGB_to_XYZ(lrgb, colour.RGB_COLOURSPACES["sRGB"], apply_cctf_decoding=False)
    np.testing.assert_allclose(lrgb_to_oklab(lrgb), colour.XYZ_to_Oklab(xyz), atol=2e-3)
    np.testing.assert_allclose(oklab_to_lrgb(lrgb_to_oklab(lrgb)), lrgb, atol=1e-9)
    lch = oklab_to_oklch(lrgb_to_oklab(lrgb))
    np.testing.assert_allclose(oklch_to_oklab(lch), lrgb_to_oklab(lrgb), atol=1e-12)


def test_in_gamut_colours_are_untouched() -> None:
    rng = np.random.default_rng(1)
    lrgb = rng.uniform(0, 1, size=(300, 3))
    np.testing.assert_array_equal(gamut_map_lrgb(lrgb), lrgb)
    rgb = rng.uniform(0, 1, size=(300, 3))
    lab = srgb_to_lab(rgb)
    np.testing.assert_allclose(lab_to_srgb(lab).rgb, lab_to_srgb(lab, method="clip").rgb)


@pytest.mark.parametrize(
    "lab",
    [[50, 0, -120], [60, -110, 60], [45, 90, 70], [85, -40, 100], [30, 60, -110], [70, 80, -10]],
)
def test_gamut_mapping_keeps_lightness_and_hue(lab: list[float]) -> None:
    from paintmixer.colorsci.convert import SRGB_WHITE, lab_to_xyz

    lin = (lab_to_xyz(np.array(lab, dtype=float), SRGB_WHITE) / 100.0) @ _M_XYZ_TO_RGB.T
    assert not in_gamut(lin)
    mapped = gamut_map_lrgb(lin)
    clipped = np.clip(lin, 0, 1)
    assert in_gamut(mapped)
    o, m_, c = (oklab_to_oklch(lrgb_to_oklab(x)) for x in (lin, mapped, clipped))

    def dh(a: np.ndarray, b: np.ndarray) -> float:
        return float(abs((a[2] - b[2] + 180) % 360 - 180))

    # lightness kept within a JND-sized step; chroma only reduced
    assert abs(m_[0] - o[0]) < 2 * JND
    assert m_[1] <= o[1] + 1e-9
    # hue kept at least as well as clipping does (usually much better)
    assert dh(m_, o) <= dh(c, o) + 0.5
    # the result is the clip of a point on the original's constant-L, constant-hue line, so it is
    # within about one JND of that line (in OKLab units; degrees are meaningless at low chroma)
    ok = lrgb_to_oklab(mapped)
    direction = np.array([np.cos(np.radians(o[2])), np.sin(np.radians(o[2]))])
    on_line = np.array([o[0], *(max(0.0, float(ok[1:] @ direction)) * direction)])
    assert float(delta_e_ok(ok, on_line)) < 1.5 * JND


def test_mapping_is_better_than_clipping_on_average() -> None:
    rng = np.random.default_rng(2)
    lab = np.column_stack([rng.uniform(20, 90, 400), rng.uniform(-130, 130, (400, 2))])
    res = lab_to_srgb(lab)
    oog = res.out_of_gamut
    assert oog.sum() > 100
    origin = lrgb_to_oklab(_lin(lab[oog]))
    mapped = lrgb_to_oklab(_srgb_decode(res.rgb[oog]))
    clipped = lrgb_to_oklab(_srgb_decode(lab_to_srgb(lab[oog], method="clip").rgb))

    def hue(x: np.ndarray) -> np.ndarray:
        out: np.ndarray = oklab_to_oklch(x)[:, 2]
        return out

    dh_map = np.abs((hue(mapped) - hue(origin) + 180) % 360 - 180)
    dh_clip = np.abs((hue(clipped) - hue(origin) + 180) % 360 - 180)
    assert np.median(dh_map) < np.median(dh_clip)
    assert np.median(np.abs(mapped[:, 0] - origin[:, 0])) < np.median(
        np.abs(clipped[:, 0] - origin[:, 0])
    )


def _lin(lab: np.ndarray) -> np.ndarray:
    from paintmixer.colorsci.convert import SRGB_WHITE, lab_to_xyz

    out: np.ndarray = (lab_to_xyz(lab, SRGB_WHITE) / 100.0) @ _M_XYZ_TO_RGB.T
    return out


def test_extremes_and_swatches() -> None:
    np.testing.assert_allclose(gamut_map_lrgb(np.array([[1.2, 1.3, 1.25]])), [[1, 1, 1]], atol=1e-6)
    np.testing.assert_array_equal(gamut_map_lrgb(np.array([[-0.1, -0.2, -0.05]])), [[0, 0, 0]])
    np.testing.assert_allclose(reflectance_to_srgb(np.ones(36)).rgb, [1, 1, 1], atol=1e-6)
    with pytest.raises(ValueError):
        lab_to_srgb([50, 0, 0], method="nearest")  # type: ignore[arg-type]
