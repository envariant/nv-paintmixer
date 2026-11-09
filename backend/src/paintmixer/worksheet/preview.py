"""Predicted swatches for a worksheet's planned drawdowns, from a fitted model.

Each row (one drawdown on one background) is predicted as a finite film at the drawdown's gap
over the model's measured substrate (``KMModel.reflectance_layer``), i.e. what the operator
should see on the -W / -B half of the chart. Substrate rows show the substrate itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from paintmixer.calibration.format import SampleType, Substrate
from paintmixer.colorsci.convert import reflectance_to_lab, reflectance_to_srgb, srgb_to_hex
from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.types import FloatArray
from paintmixer.worksheet.plan import WorksheetPlan


@dataclass(frozen=True)
class RowPreview:
    sample_id: str
    hex: str
    lab: tuple[float, float, float]


def preview_plan(
    plan: WorksheetPlan,
    model: KMModel,
    model_ids: Sequence[str],
    tau: FloatArray,
    substrate_white: FloatArray,
    substrate_black: FloatArray,
) -> dict[str, RowPreview]:
    """Predicted colour per sample id; rows with paints missing from the model are left out."""
    pos = {p: i for i, p in enumerate(model_ids)}
    out: dict[str, RowPreview] = {}
    reqs: list[tuple[str, FloatArray, float, FloatArray]] = []
    direct: list[tuple[str, FloatArray]] = []
    for d in plan.drawdowns:
        for sid, sub, stype in d.sample_ids():
            sub_r = substrate_white if sub == Substrate.WHITE else substrate_black
            if stype in (SampleType.SUBSTRATE_WHITE, SampleType.SUBSTRATE_BLACK):
                direct.append((sid, sub_r))
                continue
            if not all(p in pos for p in d.components):
                continue
            c = np.zeros(model.n_paints)
            for p, f in d.components.items():
                c[pos[p]] = f
            reqs.append((sid, c / c.sum(), d.gap_um, sub_r))
    if reqs:
        C = np.stack([r[1] for r in reqs])
        thick = np.stack([tau * r[2] for r in reqs])
        subs = np.stack([r[3] for r in reqs])
        direct += list(
            zip([r[0] for r in reqs], model.reflectance_layer(C, thick, subs), strict=True)
        )
    if direct:
        R = np.stack([r for _, r in direct])
        lab = reflectance_to_lab(R)
        rgb = reflectance_to_srgb(R).rgb
        for i, (sid, _) in enumerate(direct):
            out[sid] = RowPreview(
                sid, srgb_to_hex(rgb[i]), (float(lab[i, 0]), float(lab[i, 1]), float(lab[i, 2]))
            )
    return out
