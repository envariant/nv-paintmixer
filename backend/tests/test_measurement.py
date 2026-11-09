from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from paintmixer.calibration.format import Substrate, parse_calibration_csv
from paintmixer.calibration.synthetic import STARTER_IDS, SyntheticTruth, synthetic_paints, true_tau
from paintmixer.colorsci import WAVELENGTHS
from paintmixer.domain import PaintInfo
from paintmixer.measurement.base import MeasurementError, MeasurementSource, MeasureRequest
from paintmixer.measurement.session import MeasureSession, load_worksheet_csv, max_pairwise_de
from paintmixer.measurement.sources import CameraSource, FileImportSource, SimulatedSource
from paintmixer.measurement.spotread import ArgyllSpotread, check_fatal, parse_spotread_output
from paintmixer.worksheet.plan import WorksheetOptions, plan_worksheet
from paintmixer.worksheet.render import plan_to_csv

DATA = Path(__file__).parent / "data" / "spotread"


def test_parse_recorded_session() -> None:
    spectra = parse_spotread_output((DATA / "session_colormunki.txt").read_text())
    assert len(spectra) == 3
    s0 = spectra[0]
    assert s0.wavelengths[0] == 380 and s0.wavelengths[-1] == 730 and len(s0.values) == 36
    assert s0.xyz == pytest.approx((84.651218, 87.817744, 73.064377))
    assert s0.lab == pytest.approx((95.093102, 0.398281, -1.127663)) and s0.lab_white == "D50"
    r = s0.reading()
    assert r.reflectance.shape == (36,)
    # percent -> 0-1; the ColorMunki's 380-730 nm grid is the canonical grid
    np.testing.assert_allclose(r.reflectance, np.array(s0.values) / 100)
    # the failed-then-retried read still yields its spectrum
    assert spectra[2].lab is not None and spectra[2].lab[2] < 0


def test_parse_wrapped_and_truncated() -> None:
    vals = [f"{v:8.3f}" for v in np.linspace(10, 40, 36)]
    text = (
        "Spectrum from 380.000 to 730.000 nm in 36 steps\n"
        + ", ".join(vals[:20])
        + ",\n"
        + ", ".join(vals[20:])
        + "\n"
    )
    (s,) = parse_spotread_output(text)
    assert s.values[-1] == 40.0 and s.xyz is None
    with pytest.raises(MeasurementError):
        parse_spotread_output("Spectrum from 380.000 to 730.000 nm in 36 steps\n 1.0, 2.0\n")
    assert parse_spotread_output("no spectra here") == []


def test_no_instrument_detection() -> None:
    assert check_fatal((DATA / "no_instrument.txt").read_text()) is None
    assert check_fatal("Unknown, inappropriate or no instrument detected\n") is not None


def test_spotread_wrapper_against_fake_instrument() -> None:
    prompts: list[str] = []
    src = ArgyllSpotread(str(DATA / "fake_spotread.py"), prompt=prompts.append, timeout=10)
    src.open()
    try:
        a = src.read(MeasureRequest("SUB-W"))
        b = src.read(MeasureRequest("TN-x-W"))
    finally:
        src.close()
    assert a.reflectance[15] > 0.8 and b.reflectance[15] < 0.3
    assert any("calibration" in p for p in prompts)
    assert isinstance(src, MeasurementSource)


def test_spotread_wrapper_retry_and_missing_instrument() -> None:
    prompts: list[str] = []
    src = ArgyllSpotread(
        str(DATA / "fake_spotread.py"), ("--fail-once",), prompt=prompts.append, timeout=10
    )
    src.open()
    r = src.read(MeasureRequest("X"))
    src.close()
    assert r.reflectance.shape == (36,)
    assert any("Reading failed" in p for p in prompts)
    bad = ArgyllSpotread(str(DATA / "fake_spotread.py"), ("--none",), timeout=10)
    with pytest.raises(MeasurementError, match="spotread -\\?"):
        bad.open()
    with pytest.raises(MeasurementError, match="not found"):
        ArgyllSpotread("definitely-not-spotread").open()


def test_file_import_source(tmp_path: Path) -> None:
    wl = list(range(380, 731, 10))
    lines = ["sample_id," + ",".join(f"r{w}" for w in wl)]
    lines.append("A," + ",".join("50" for _ in wl))  # percent
    lines.append("A," + ",".join("52" for _ in wl))
    lines.append("B," + ",".join("0.2" for _ in wl))
    src = FileImportSource(text="\n".join(lines))
    assert src.read(MeasureRequest("A")).reflectance[0] == pytest.approx(0.5)
    assert src.read(MeasureRequest("A")).reflectance[0] == pytest.approx(0.52)
    assert src.read(MeasureRequest("B")).reflectance[0] == pytest.approx(0.2)
    with pytest.raises(MeasurementError):
        src.read(MeasureRequest("C"))


def _truth() -> SyntheticTruth:
    return SyntheticTruth(synthetic_paints(), true_tau(), 0.0, 0.5)


def test_simulated_source_bias_and_noise() -> None:
    t = _truth()
    clean = SimulatedSource(t.model, t.ids, noise=0.0)
    req = MeasureRequest("m", Substrate.WHITE, {"titanium-white": 0.8, "phthalo-blue": 0.2}, 150)
    r0 = clean.read(req).reflectance
    biased = SimulatedSource(t.model, t.ids, noise=0.0, gain=1.05, offset=0.01)
    np.testing.assert_allclose(biased.read(req).reflectance, np.clip(1.05 * r0 + 0.01, 0, 1.2))
    noisy = SimulatedSource(t.model, t.ids, noise=0.002, seed=1)
    d = np.stack([noisy.read(req).reflectance - r0 for _ in range(200)])
    assert 0.0015 < d.std() < 0.0025
    opaque = clean.read(MeasureRequest("cup", None, {"titanium-white": 1.0})).reflectance
    np.testing.assert_allclose(opaque, t.model.reflectance(np.eye(5)[0]))
    with pytest.raises(NotImplementedError):
        CameraSource().open()


def _worksheet(tmp_path: Path, paints: dict[str, PaintInfo]) -> Path:
    plan = plan_worksheet(
        [paints[p] for p in STARTER_IDS],
        WorksheetOptions(n_random=2, n_dark=1, n_neutral_per_level=0),
    )
    p = tmp_path / "worksheet.csv"
    p.write_text(plan_to_csv(plan))
    return p


def test_measure_session_writes_resumes_and_validates(
    tmp_path: Path, paints: dict[str, PaintInfo]
) -> None:
    ws = _worksheet(tmp_path, paints)
    samples = load_worksheet_csv(ws.read_text())
    out = tmp_path / "cal.csv"
    t = _truth()
    answers = iter([""] * 10 + ["q"])
    s1 = MeasureSession(
        samples,
        SimulatedSource(t.model, t.ids, noise=0.0001, seed=1),
        out,
        ask=lambda _m: next(answers),
        say=lambda _m: None,
    )
    sum1 = s1.run()
    assert sum1.quit_early and len(sum1.measured) == 10
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 10 and rows[0]["n_readings"] == "3" and rows[0]["sd400"]
    # resume: only the remaining samples are measured
    s2 = MeasureSession(
        samples,
        SimulatedSource(t.model, t.ids, noise=0.0001, seed=2),
        out,
        ask=lambda _m: "",
        say=lambda _m: None,
    )
    sum2 = s2.run()
    assert sum2.already_done == 10 and len(sum2.measured) == len(samples) - 10
    rep = parse_calibration_csv(out.read_text(), paints)
    assert rep.ok, rep.errors[:3]
    assert len(rep.samples) == len(samples)
    assert all(s.spread is not None and s.n_readings == 3 for s in rep.samples)


def test_measure_session_warns_on_inconsistent_readings(
    tmp_path: Path, paints: dict[str, PaintInfo]
) -> None:
    ws = _worksheet(tmp_path, paints)
    samples = load_worksheet_csv(ws.read_text())[:2]
    t = _truth()
    noisy = SimulatedSource(t.model, t.ids, noise=0.03, seed=0)
    said: list[str] = []
    answers = iter(["", "r", "a", "", "a"])
    s = MeasureSession(
        samples, noisy, tmp_path / "o.csv", ask=lambda _m: next(answers, "a"), say=said.append
    )
    summary = s.run()
    assert any("repeat readings differ" in x for x in said)
    assert summary.warnings and summary.measured[0].accepted_with_warning


def test_session_skip_and_masses(tmp_path: Path, paints: dict[str, PaintInfo]) -> None:
    ws = _worksheet(tmp_path, paints)
    samples = [
        s for s in load_worksheet_csv(ws.read_text()) if s.sample_id.startswith("TN-phthalo-blue-5")
    ]
    t = _truth()
    answers = iter(["phthalo-blue:0.45;titanium-white:9.55", "", "s"])
    out = tmp_path / "m.csv"
    summary = MeasureSession(
        samples,
        SimulatedSource(t.model, t.ids, noise=0.0001),
        out,
        ask=lambda _m: next(answers),
        say=lambda _m: None,
        ask_masses=True,
    ).run()
    assert summary.skipped == ["TN-phthalo-blue-5-B"]
    rep = parse_calibration_csv(out.read_text(), paints)
    assert rep.samples[0].masses_g == {"phthalo-blue": 0.45, "titanium-white": 9.55}


def test_max_pairwise_de() -> None:
    r = np.full((3, 36), 0.5)
    assert max_pairwise_de(r) == 0.0
    r[2] += 0.05
    assert max_pairwise_de(r) > 1.0
    assert WAVELENGTHS.size == 36


def test_cli_measure_session_simulated(tmp_path: Path, paints: dict[str, PaintInfo]) -> None:
    from typer.testing import CliRunner

    from paintmixer.cli import app

    ws = _worksheet(tmp_path, paints)
    n = len(load_worksheet_csv(ws.read_text()))
    out = tmp_path / "cli.csv"
    res = CliRunner().invoke(
        app,
        [
            "measure",
            "session",
            "--worksheet",
            str(ws),
            "--out",
            str(out),
            "--source",
            "simulated",
            "--max-de",
            "50",
        ],
        input="\n" * (n + 5),
    )
    assert res.exit_code == 0, res.output
    assert f"measured {n}" in res.output
    assert parse_calibration_csv(out.read_text(), paints).ok
