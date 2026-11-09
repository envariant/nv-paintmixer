"""Colour for gamut boundaries and a self-contained SVG chart of a gamut.

The chart is a small-multiples view: one CIELAB a*b* panel per L* slice, each hue wedge filled
from neutral at the centre to the boundary colour at the edge, on a neutral mid-grey surround
(about L* 53) so that neither light nor dark slices are judged against white. Colours are the
D65 sRGB rendering of the Lab values, gamut-mapped (CSS Color 4) where sRGB cannot show them,
so a wedge looks less saturated on screen than the paint will be; the outline is the real
boundary.
"""

from __future__ import annotations

import math
from html import escape

import numpy as np

from paintmixer.colorsci.convert import lab_to_srgb
from paintmixer.colorsci.types import FloatArray
from paintmixer.solver.gamut import Gamut, GamutSlice

SURROUND = "#7f7f7f"
PANEL = 180  # px, square a*b* panel
GAP = 16
RINGS = 5  # radial colour steps per wedge
CHROMA_STEP = 20.0  # grid ring spacing


def _hexes(lab: FloatArray) -> list[str]:
    """Hex strings for Lab rows of shape (n, 3) (one vectorised sRGB conversion)."""
    v = np.clip(np.round(lab_to_srgb(lab).rgb * 255.0), 0, 255).astype(int)
    return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in v.tolist()]


def boundary_hex(sl: GamutSlice) -> list[str | None]:
    """sRGB hex of each boundary point of a slice; ``None`` where the bin has no samples."""
    lab = np.stack([np.full(sl.a.shape, sl.L), sl.a, sl.b], axis=-1)
    hexes = _hexes(lab)
    return [h if c > 0 else None for h, c in zip(hexes, sl.chroma.tolist(), strict=True)]


def _scale_limit(gamut: Gamut) -> float:
    cmax = max((float(sl.chroma.max()) for sl in gamut.slices), default=0.0)
    return max(40.0, math.ceil(cmax / CHROMA_STEP) * CHROMA_STEP)


def _panel(sl: GamutSlice, x0: float, y0: float, limit: float) -> list[str]:
    half = PANEL / 2.0
    cx = cy = half  # panel-local coordinates; the nested <svg> clips to the panel
    k = (half - 6.0) / limit  # px per chroma unit

    def pt(a: float, b: float) -> str:
        return f"{cx + a * k:.1f},{cy - b * k:.1f}"  # +b* up

    # data-* attributes let a client map a click back to Lab:
    # a* = (x - cx) / k, b* = (cy - y) / k, L* = data-L (in panel pixels)
    out = [
        f'<svg class="slice" x="{x0}" y="{y0}" width="{PANEL}" height="{PANEL}" '
        f'data-L="{sl.L:g}" data-cx="{cx:g}" data-cy="{cy:g}" data-px-per-chroma="{k:.6g}">',
        f'<rect width="{PANEL}" height="{PANEL}" fill="{SURROUND}" stroke="#6b6b6b"/>',
    ]
    # chroma grid and axes
    c = CHROMA_STEP
    while c <= limit + 1e-9:
        out.append(
            f'<circle cx="{cx}" cy="{cy}" r="{c * k:.1f}" fill="none" stroke="#8c8c8c" '
            'stroke-width="0.6"/>'
        )
        c += CHROMA_STEP
    out.append(
        f'<path d="M4,{cy}H{PANEL - 4}M{cx},4V{PANEL - 4}" stroke="#8c8c8c" stroke-width="0.6"/>'
    )
    # wedges: segment between consecutive boundary points, split into rings
    n = sl.a.size
    a1, b1 = sl.a, sl.b
    a2, b2 = np.roll(sl.a, -1), np.roll(sl.b, -1)
    t = np.linspace(0.0, 1.0, RINGS + 1)
    tm = (t[:-1] + t[1:]) / 2.0
    mid_a = (a1 + a2)[:, None] / 2.0 * tm[None, :]
    mid_b = (b1 + b2)[:, None] / 2.0 * tm[None, :]
    lab = np.stack([np.full(mid_a.shape, sl.L), mid_a, mid_b], axis=-1).reshape(-1, 3)
    fills = _hexes(lab)
    for i in range(n):
        if sl.chroma[i] <= 0 and sl.chroma[(i + 1) % n] <= 0:
            continue
        for j in range(RINGS):
            s0, s1 = t[j], t[j + 1]
            quad = " ".join(
                [
                    pt(a1[i] * s0, b1[i] * s0),
                    pt(a1[i] * s1, b1[i] * s1),
                    pt(a2[i] * s1, b2[i] * s1),
                    pt(a2[i] * s0, b2[i] * s0),
                ]
            )
            f = fills[i * RINGS + j]
            out.append(f'<polygon points="{quad}" fill="{f}" stroke="{f}" stroke-width="0.4"/>')
    outline = " ".join(pt(a, b) for a, b in zip(a1.tolist(), b1.tolist(), strict=True))
    out.append(
        f'<polygon class="boundary" points="{outline}" fill="none" stroke="#1f1f1f" '
        'stroke-width="1.2" stroke-linejoin="round"/>'
    )
    out.append(f'<text x="8" y="18" font-size="13" fill="#111">L* {sl.L:g}</text>')
    out.append(
        f'<text x="{PANEL - 8}" y="{PANEL - 8}" font-size="10" fill="#222" '
        f'text-anchor="end">max C* {float(sl.chroma.max()):.0f}</text>'
    )
    out.append("</svg>")
    return out


def gamut_svg(
    gamut: Gamut,
    title: str,
    subtitle: str = "",
    columns: int = 5,
    chroma_scale: float | None = None,
) -> str:
    """Standalone SVG document: one a*b* panel per L* slice, all on one chroma scale.

    ``chroma_scale`` fixes the C* at the panel edge (to compare charts of different models);
    by default it is the gamut's maximum chroma rounded up to the grid step."""
    slices = gamut.slices
    cols = max(1, min(columns, len(slices) or 1))
    rows = max(1, math.ceil(len(slices) / cols))
    head = 58
    foot = 26
    width = GAP + cols * (PANEL + GAP)
    height = head + rows * (PANEL + GAP) + foot
    limit = chroma_scale if chroma_scale else _scale_limit(gamut)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, sans-serif">',
        f"<title>{escape(title)}</title>",
        f'<rect width="{width}" height="{height}" fill="{SURROUND}"/>',
        f'<text x="{GAP}" y="26" font-size="17" font-weight="600" fill="#111">'
        f"{escape(title)}</text>",
        f'<text x="{GAP}" y="45" font-size="12" fill="#1a1a1a">{escape(subtitle)}</text>',
    ]
    for idx, sl in enumerate(slices):
        r, c = divmod(idx, cols)
        out.extend(_panel(sl, GAP + c * (PANEL + GAP), head + r * (PANEL + GAP), limit))
    out.append(
        f'<text x="{GAP}" y="{height - 9}" font-size="10" fill="#1a1a1a">'
        f"a* right, b* up; rings every {CHROMA_STEP:g} C* (scale ±{limit:g}). D65 sRGB, "
        "gamut-mapped where the screen cannot show the colour.</text>"
    )
    out.append("</svg>")
    return "\n".join(out)
