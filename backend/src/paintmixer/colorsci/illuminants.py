"""Illuminant catalogue for the UI, and how a mixture *looks* under each illuminant.

Two separate uses:

* **Solve under** (``SolveRequest.illuminant``): the illuminant the match is optimised for.
* **Preview under**: what the target and a candidate look like under another light. The swatch
  is shown on an sRGB (D65) display, so the colour seen under the illuminant is chromatically
  adapted to D65 (CAT02, full adaptation) before it is converted to sRGB. The UI never shifts
  hues itself; it shows these values.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from paintmixer.colorsci.convert import lab_to_srgb, srgb_to_hex, xyz_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.spectral import Illuminant, reflectance_to_xyz, white_point
from paintmixer.colorsci.types import ArrayLike, FloatArray


@dataclass(frozen=True)
class Member:
    code: Illuminant
    cct: int


@dataclass(frozen=True)
class Series:
    id: str
    name: str
    description: str
    default: Illuminant
    members: tuple[Member, ...]


SERIES: tuple[Series, ...] = (
    Series(
        "D",
        "D series",
        "Daylight",
        Illuminant.D65,
        (
            Member(Illuminant.D50, 5003),
            Member(Illuminant.D55, 5503),
            Member(Illuminant.D65, 6504),
            Member(Illuminant.D75, 7504),
            Member(Illuminant.D93, 9300),
        ),
    ),
    Series("A", "A", "Incandescent / tungsten", Illuminant.A, (Member(Illuminant.A, 2856),)),
    Series(
        "F",
        "F series",
        "Fluorescent",
        Illuminant.F11,
        (
            Member(Illuminant.F2, 4230),
            Member(Illuminant.F7, 6500),
            Member(Illuminant.F11, 4000),
            Member(Illuminant.F12, 3000),
        ),
    ),
    Series(
        "LED",
        "LED series",
        "White LEDs",
        Illuminant.LED_B3,
        (
            Member(Illuminant.LED_B1, 2733),
            Member(Illuminant.LED_B2, 2998),
            Member(Illuminant.LED_B3, 4103),
            Member(Illuminant.LED_B4, 5109),
            Member(Illuminant.LED_B5, 6598),
        ),
    ),
    Series(
        "ID",
        "ID series",
        "Indoor daylight",
        Illuminant.ID65,
        (
            Member(Illuminant.ID50, 5003),
            Member(Illuminant.ID65, 6504),
        ),
    ),
)

CCT: dict[Illuminant, int] = {m.code: m.cct for s in SERIES for m in s.members}
SERIES_OF: dict[Illuminant, Series] = {m.code: s for s in SERIES for m in s.members}


def nearest_in_series(series_id: str, current: Illuminant | str) -> Illuminant:
    """Switching series keeps the member closest in colour temperature to ``current``."""
    s = next(x for x in SERIES if x.id == series_id)
    k = CCT[Illuminant(current)]
    return min(s.members, key=lambda m: abs(m.cct - k)).code


# CAT02 (CIECAM02) cone-response matrix
_M_CAT02: FloatArray = np.array(
    [[0.7328, 0.4296, -0.1624], [-0.7036, 1.6975, 0.0061], [0.0030, 0.0136, 0.9834]]
)
_M_CAT02_INV: FloatArray = np.linalg.inv(_M_CAT02)


def adapt_to_d65(xyz: ArrayLike, illuminant: Illuminant | str) -> FloatArray:
    """Von Kries / CAT02 full adaptation of XYZ seen under ``illuminant`` to the D65 white."""
    src = _M_CAT02 @ white_point(illuminant)
    dst = _M_CAT02 @ white_point(Illuminant.D65)
    m = _M_CAT02_INV @ np.diag(dst / src) @ _M_CAT02
    out: FloatArray = np.asarray(xyz, dtype=np.float64) @ m.T
    return out


@dataclass(frozen=True)
class Appearance:
    illuminant: Illuminant
    lab: FloatArray  # CIELAB under the illuminant, relative to its own white
    display_lab: FloatArray  # adapted to D65, what an sRGB display should show
    hex: str
    out_of_srgb_gamut: bool


def appearance(reflectance: ArrayLike, illuminant: Illuminant | str) -> Appearance:
    ill = Illuminant(illuminant)
    xyz = reflectance_to_xyz(reflectance, ill)
    lab = xyz_to_lab(xyz, white_point(ill))
    display = xyz_to_lab(adapt_to_d65(xyz, ill), white_point(Illuminant.D65))
    rgb = lab_to_srgb(display)
    return Appearance(ill, lab, display, srgb_to_hex(rgb.rgb), bool(rgb.out_of_gamut))


def de_under(a: ArrayLike, b: ArrayLike, illuminant: Illuminant | str) -> float:
    """dE2000 between two reflectances, both seen under ``illuminant``."""
    ill = Illuminant(illuminant)
    w = white_point(ill)
    la = xyz_to_lab(reflectance_to_xyz(a, ill), w)
    lb = xyz_to_lab(reflectance_to_xyz(b, ill), w)
    return float(delta_e_2000(la, lb))
