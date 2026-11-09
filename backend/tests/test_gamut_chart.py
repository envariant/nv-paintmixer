from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np

from paintmixer.colorsci.convert import hex_to_srgb, srgb_to_lab
from paintmixer.solver.gamut import HUE_BINS, Gamut, GamutSlice, compute_gamut
from paintmixer.solver.gamut_chart import boundary_hex, gamut_svg
from tests.solver_helpers import pool_model

NS = "{http://www.w3.org/2000/svg}"


def _slice(L: float, chroma: np.ndarray) -> GamutSlice:
    hue = (np.arange(HUE_BINS) + 0.5) * 360.0 / HUE_BINS
    rad = np.radians(hue)
    return GamutSlice(L, hue, chroma, chroma * np.cos(rad), chroma * np.sin(rad))


def test_boundary_hex_matches_lab() -> None:
    chroma = np.full(HUE_BINS, 20.0)
    chroma[5] = 0.0
    sl = _slice(60.0, chroma)
    hexes = boundary_hex(sl)
    assert len(hexes) == HUE_BINS and hexes[5] is None
    h0 = hexes[0]
    assert h0 is not None
    lab = srgb_to_lab(hex_to_srgb(h0))
    assert np.allclose(lab, [60.0, sl.a[0], sl.b[0]], atol=1.0)  # in sRGB: only rounding


def test_svg_layout_and_scale() -> None:
    g = Gamut([_slice(L, np.full(HUE_BINS, 30.0)) for L in (20, 40, 60, 80)], 15, 85, 100)
    root = ET.fromstring(gamut_svg(g, "T <&>", "sub", columns=3))
    panels = root.findall(f"{NS}svg")
    assert [p.get("data-L") for p in panels] == ["20", "40", "60", "80"]
    assert root.findtext(f"{NS}title") == "T <&>"
    assert {p.get("y") for p in panels[:3]} != {panels[3].get("y")}  # 3 per row
    k_auto = float(panels[0].get("data-px-per-chroma") or 0)
    fixed = ET.fromstring(gamut_svg(g, "T", chroma_scale=120.0)).findall(f"{NS}svg")[0]
    assert float(fixed.get("data-px-per-chroma") or 0) < k_auto  # 40 -> 120: smaller


def test_light_slices_are_filled_by_tints() -> None:
    """Pale colours between two hues (lilac, pale teal) are reachable with three paints and
    white; the boundary of light slices must not collapse to the two-paint tint lines."""
    g = compute_gamut(pool_model(5))
    for sl in g.slices:
        if 70 <= sl.L <= 80:
            assert (sl.chroma > 5.0).sum() >= 24, (sl.L, sl.chroma.round(1).tolist())
