from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest

from paintmixer.calibration.fit import FitError, FitOptions, FitResult, _evaluate, fit_calibration
from paintmixer.calibration.format import CalibrationSampleData, SampleType
from paintmixer.calibration.synthetic import (
    POOL_IDS,
    SyntheticTruth,
    generate_calibration,
    render,
    synthetic_paints,
)
from paintmixer.colorsci import delta_e_2000, reflectance_to_lab
from paintmixer.domain import PaintInfo
from paintmixer.worksheet.plan import WorksheetOptions


def _fit(
    ids: Sequence[str] | None = None, noise: float = 0.002, seed: int = 7, **kw: Any
) -> tuple[list[CalibrationSampleData], SyntheticTruth, dict[str, PaintInfo], FitResult]:
    samples, truth, _ = generate_calibration(
        synthetic_paints(ids) if ids else synthetic_paints(), noise=noise, seed=seed, **kw
    )
    paints = {p.info.id: p.info for p in truth.paints}
    return samples, truth, paints, fit_calibration(samples, paints)


@pytest.mark.parametrize("ids", [None, POOL_IDS], ids=["starter5", "pool9"])
def test_holdout_accuracy_on_synthetic(ids: Sequence[str] | None) -> None:
    samples, truth, _, r = _fit(ids)
    hold = [s for s in samples if s.holdout]
    assert r.holdout.method == "flagged" and r.holdout.n_samples == len(hold) > 0
    pred, _, de_meas = _evaluate(
        hold, r.model, r.paint_ids, r.tau, r.substrate_white, r.substrate_black
    )
    clean = np.stack([render(truth, s.components, s.substrate, s.effective_gap_um) for s in hold])
    de_true = delta_e_2000(reflectance_to_lab(pred), reflectance_to_lab(clean))
    # Acceptance: model vs noise-free ground truth on the hold-out set
    assert de_true.mean() < 0.5, de_true.mean()
    # Against the noisy measurements the model sits at the measurement-noise floor
    assert r.holdout.mean_de == pytest.approx(de_meas.mean())
    assert r.holdout.mean_de < r.holdout.noise_floor_mean_de + 0.2
    assert r.holdout.mean_rms < 0.0025


def test_low_noise_holdout_report_below_half_de() -> None:
    _, _, _, r = _fit(noise=0.0003)
    assert r.holdout.mean_de < 0.5


def test_parameter_recovery() -> None:
    _, truth, _, r = _fit()
    for i, pid in enumerate(r.paint_ids):
        j = truth.ids.index(pid)
        k_err = np.median(np.abs(r.K[i] / truth.paints[j].K - 1))
        s_err = np.median(np.abs(r.S[i] / truth.paints[j].S - 1))
        assert k_err < 0.05, (pid, k_err)
        assert s_err < 0.15, (pid, s_err)
    assert np.median(np.abs(r.tau / truth.tau - 1)) < 0.03
    assert r.paint_ids[0] == "titanium-white"
    np.testing.assert_array_equal(r.S[0], 1.0)


def test_deterministic() -> None:
    samples, _, paints, r1 = _fit()
    r2 = fit_calibration(samples, paints)
    np.testing.assert_array_equal(r1.K, r2.K)


def test_kfold_when_no_holdout_flags() -> None:
    samples, truth, _ = generate_calibration(synthetic_paints())
    for s in samples:
        s.holdout = False
    paints = {p.info.id: p.info for p in truth.paints}
    r = fit_calibration(samples, paints, FitOptions(k_folds=3))
    assert r.holdout.method == "kfold"
    n_mix = sum(s.type == SampleType.MIXTURE for s in samples)
    assert r.holdout.n_samples == n_mix
    assert r.holdout.mean_de < r.holdout.noise_floor_mean_de + 0.3


def test_outlier_flagged() -> None:
    samples, truth, _ = generate_calibration(synthetic_paints())
    bad = next(s for s in samples if s.type == SampleType.MIXTURE and not s.holdout)
    bad.reflectance = np.clip(bad.reflectance + 0.04, 0, 1)
    paints = {p.info.id: p.info for p in truth.paints}
    r = fit_calibration(samples, paints)
    flagged = [x.sample_id for x in r.residuals if x.outlier]
    assert flagged == [bad.sample_id]
    assert any("outlier" in w for w in r.warnings)


def test_insufficient_data_warnings() -> None:
    samples, truth, _ = generate_calibration(
        synthetic_paints(),
        options=WorksheetOptions(n_random=0, n_dark=0, n_neutral_per_level=0, include_pairs=False),
    )
    samples = [
        s
        for s in samples
        if not (s.type == SampleType.TINT and "phthalo-blue" in s.components)
        and not (s.sample_id.startswith("MT-arylide-yellow"))
    ]
    paints = {p.info.id: p.info for p in truth.paints}
    r = fit_calibration(samples, paints)
    text = " ".join(r.warnings)
    assert "phthalo-blue: no tint with white" in text
    assert "arylide-yellow: no masstone" in text
    assert "Too few mixtures" in text
    assert r.holdout.method == "none"


def test_unknown_paint_raises() -> None:
    samples, truth, _ = generate_calibration(synthetic_paints())
    paints = {p.info.id: p.info for p in truth.paints if p.info.id != "carbon-black"}
    with pytest.raises(FitError):
        fit_calibration(samples, paints)


def test_progress_callback() -> None:
    samples, truth, _ = generate_calibration(synthetic_paints())
    paints = {p.info.id: p.info for p in truth.paints}
    seen: list[float] = []
    fit_calibration(samples, paints, progress=lambda f, _m: seen.append(f))
    assert seen[0] < seen[-1] == 1.0


def test_saunderson_options_are_respected() -> None:
    samples, truth, _ = generate_calibration(synthetic_paints(), k2=0.6)
    paints = {p.info.id: p.info for p in truth.paints}
    good = fit_calibration(samples, paints, FitOptions(k2=0.6))
    assert good.k2 == 0.6
    assert dataclasses.asdict(good.holdout)["mean_rms"] < 0.0025
