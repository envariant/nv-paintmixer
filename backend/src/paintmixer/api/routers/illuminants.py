"""Illuminant catalogue and appearance under a preview light."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter

from paintmixer.api.errors import ERROR_RESPONSES
from paintmixer.api.schemas import (
    AppearanceOut,
    AppearanceRequest,
    AppearanceResponse,
    AppearanceUnderOut,
    IlluminantMemberOut,
    IlluminantSeriesOut,
)
from paintmixer.colorsci.illuminants import CCT, SERIES, Appearance, appearance, de_under

router = APIRouter(tags=["illuminants"], responses=ERROR_RESPONSES)


def _range(ccts: list[int]) -> str:
    return f"{min(ccts)}–{max(ccts)} K" if len(ccts) > 1 else f"{ccts[0]} K"


@router.get("/illuminants", response_model=list[IlluminantSeriesOut])
def list_illuminants() -> list[IlluminantSeriesOut]:
    """Series → members with nominal CCT. Switching series in the UI keeps the closest CCT."""
    return [
        IlluminantSeriesOut(
            id=s.id,
            name=s.name,
            description=s.description,
            default=s.default,
            range=_range([m.cct for m in s.members]),
            members=[IlluminantMemberOut(code=m.code, cct=m.cct) for m in s.members],
        )
        for s in SERIES
    ]


def _out(a: Appearance) -> AppearanceOut:
    return AppearanceOut(
        lab=[round(float(x), 4) for x in a.lab],
        display_lab=[round(float(x), 4) for x in a.display_lab],
        hex=a.hex,
        out_of_srgb_gamut=a.out_of_srgb_gamut,
    )


@router.post("/appearance", response_model=AppearanceResponse)
def get_appearance(body: AppearanceRequest) -> AppearanceResponse:
    """Target and candidates as seen under each illuminant, adapted for display, with dE2000.

    Cheap (no model needed): the client sends ``reference_spectrum`` and the candidates'
    ``predicted_spectrum`` from ``POST /solve`` whenever the preview light changes.
    """
    ref = np.asarray(body.reference, dtype=np.float64)
    under = []
    for ill in body.illuminants:
        specs = [np.asarray(s, dtype=np.float64) for s in body.spectra]
        under.append(
            AppearanceUnderOut(
                illuminant=ill,
                cct=CCT[ill],
                reference=_out(appearance(ref, ill)),
                spectra=[_out(appearance(s, ill)) for s in specs],
                de2000=[round(de_under(ref, s, ill), 4) for s in specs],
            )
        )
    return AppearanceResponse(under=under)
