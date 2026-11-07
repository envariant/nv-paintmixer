"""Serialisation and human-readable summaries of a calibration fit."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np

from paintmixer.calibration.fit import FitResult
from paintmixer.colorsci.spectral import WAVELENGTHS


def _clean(v: Any) -> Any:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def fit_result_to_dict(r: FitResult, *, include_predictions: bool = False) -> dict[str, Any]:
    residuals = []
    for x in r.residuals:
        d = dataclasses.asdict(x)
        if not include_predictions:
            d.pop("predicted")
        residuals.append(d)
    out = {
        "wavelengths": WAVELENGTHS.tolist(),
        "paint_ids": r.paint_ids,
        "K": np.round(r.K, 7).tolist(),
        "S": np.round(r.S, 7).tolist(),
        "tau": np.round(r.tau, 9).tolist(),
        "k1": r.k1,
        "k2": r.k2,
        "substrate_white": np.round(r.substrate_white, 6).tolist(),
        "substrate_black": np.round(r.substrate_black, 6).tolist(),
        "holdout": r.holdout.as_dict(),
        "residuals": residuals,
        "warnings": r.warnings,
        "diagnostics": r.diagnostics,
    }
    cleaned: dict[str, Any] = _clean(out)
    return cleaned


def fit_summary_text(r: FitResult) -> str:
    h = r.holdout
    d = r.diagnostics
    lines = [
        f"Fitted {len(r.paint_ids)} paints on {d['n_train']} samples "
        f"({d['nfev']} evaluations, {d['duration_s']:.1f} s).",
        f"Training: mean dE2000 {d['train_mean_de']:.2f}, max {d['train_max_de']:.2f}, "
        f"RMS reflectance {d['train_mean_rms']:.4f}.",
    ]
    if h.method == "none":
        lines.append("Hold-out: not available (no holdout flags and too few mixtures).")
    else:
        label = "flagged hold-out samples" if h.method == "flagged" else "k-fold cross-validation"
        lines.append(
            f"Hold-out ({label}, n={h.n_samples}): mean dE2000 {h.mean_de:.2f}, median "
            f"{h.median_de:.2f}, 95th pct {h.p95_de:.2f}, max {h.max_de:.2f}; "
            f"measurement noise alone ~ {h.noise_floor_mean_de:.2f}."
        )
    worst = sorted(r.residuals, key=lambda x: -x.de2000)[:5]
    lines.append("Worst samples: " + ", ".join(f"{w.sample_id} ({w.de2000:.2f})" for w in worst))
    lines += [f"warning: {w}" for w in r.warnings]
    return "\n".join(lines)
