from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from paintmixer.api.services import selftest_thresholds, settings_from_db
from paintmixer.cli import app, simulated_selftest_source
from paintmixer.colorsci import WAVELENGTHS
from paintmixer.measurement.selftest import (
    FAIL,
    PASS,
    WARN,
    SelftestReport,
    SelftestRun,
    SelftestThresholds,
    analyse_tile,
    default_output_root,
    format_report,
    run_selftest,
    write_outputs,
)
from paintmixer.measurement.sources import FileImportSource
from paintmixer.measurement.spotread import (
    detect_instruments,
    parse_port_list,
    parse_spotread_output,
)

DATA = Path(__file__).parent / "data" / "spotread"
FAKE = str(DATA / "fake_spotread.py")


def quiet(**kw: Any) -> SelftestRun:
    """run_selftest with an operator who always presses Enter."""
    return run_selftest(ask=lambda _m: "", say=lambda _m: None, **kw)


def status(report: SelftestReport, name: str) -> str:
    return str(next(c.status for c in report.checks if c.name == name))


def tile_csv(spectra: list[np.ndarray], sid: str = "WHITE-TILE") -> str:
    lines = ["sample_id," + ",".join(f"r{w:.0f}" for w in WAVELENGTHS)]
    lines += [sid + "," + ",".join(f"{v:.5f}" for v in s) for s in spectra]
    return "\n".join(lines) + "\n"


# --- detection ------------------------------------------------------------------------------


def test_parse_port_list_fixtures() -> None:
    ports = parse_port_list((DATA / "usage_colormunki.txt").read_text())
    assert [p.index for p in ports] == [1, 2]
    assert ports[0].instrument == "X-Rite ColorMunki" and ports[1].instrument is None
    assert parse_port_list((DATA / "usage_no_ports.txt").read_text()) == []
    dis = parse_port_list((DATA / "usage_disabled.txt").read_text())
    assert dis[0].disabled and dis[0].instrument == "GretagMacbeth i1 Pro"
    # real capture from a machine without an instrument: the list never appears
    assert parse_port_list((DATA / "no_instrument.txt").read_text()) == []


def test_detect_instruments_with_fake_spotread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_SPOTREAD_PORTS", "colormunki")
    det = detect_instruments(FAKE, timeout=10)
    assert [p.instrument for p in det.instruments] == ["X-Rite ColorMunki"] and not det.timed_out
    monkeypatch.setenv("FAKE_SPOTREAD_PORTS", "disabled")
    assert detect_instruments(FAKE, timeout=10).instruments == []
    monkeypatch.setenv("FAKE_SPOTREAD_PORTS", "hang")
    hung = detect_instruments(FAKE, timeout=1.5)
    assert hung.timed_out and hung.instruments == []
    assert detect_instruments("no-such-spotread").error is not None


def test_missing_instrument_cli_prints_macos_help(tmp_path: Path) -> None:
    env = {
        "FAKE_SPOTREAD_PORTS": "none",
        "PAINTMIXER_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}",
    }
    res = CliRunner().invoke(
        app, ["measure", "selftest", "--spotread", FAKE, "--out-dir", str(tmp_path)], env=env
    )
    assert res.exit_code == 2
    out = res.output
    for needle in ("brew install argyll-cms", "USB port or cable", "X-Rite", "sudo spotread -?"):
        assert needle in out, needle
    assert not any(tmp_path.glob("2*"))  # nothing written
    res = CliRunner().invoke(
        app, ["measure", "selftest", "--spotread", "no-such-spotread"], env=env
    )
    assert res.exit_code == 2 and "not found" in res.output


# --- simulated runs -------------------------------------------------------------------------


def test_clean_run_passes_and_writes_outputs(tmp_path: Path) -> None:
    run = quiet(source=simulated_selftest_source(noise=0.001, seed=1), n=10, replace=True)
    r = run.report
    assert r.verdict == PASS, format_report(r)
    assert r.n == 10 and len(r.de_vs_mean) == 10 and len(r.mean) == len(r.std) == len(WAVELENGTHS)
    assert r.repeat_max_de < 0.5 and r.repeat_mean_de <= r.repeat_max_de
    assert abs(r.drift_de) < 0.2
    out = write_outputs(run, tmp_path)
    data = json.loads((out / "report.json").read_text())
    assert data["verdict"] == PASS and data["thresholds"]["warn_de"] == 0.5
    rows = list(csv.DictReader((out / "spectra.csv").open()))
    assert len(rows) == 10 and rows[0]["sample_id"] == "WHITE-TILE"
    assert not (out / "spectra_raw.csv").exists()  # simulator has no native grid
    # the saved spectra replay through the file source to the same verdict
    replay = quiet(source=FileImportSource(out / "spectra.csv"), n=10)
    assert replay.report.verdict == PASS
    np.testing.assert_allclose(replay.report.mean, r.mean, atol=1e-6)


def test_noisy_run_warns_or_fails() -> None:
    r = quiet(source=simulated_selftest_source(noise=0.02, seed=2), n=10).report
    assert r.verdict in (WARN, FAIL)
    assert status(r, "repeatability") != PASS and r.repeat_max_de > 0.5


def test_drifting_run_is_flagged() -> None:
    r = quiet(source=simulated_selftest_source(noise=0.0005, drift=0.004, seed=3), n=12).report
    assert status(r, "drift") in (WARN, FAIL), format_report(r)
    assert r.drift_de > 0.5 and r.drift_slope_de_per_reading > 0
    assert r.verdict != PASS
    steady = quiet(source=simulated_selftest_source(noise=0.0005, seed=3), n=12).report
    assert status(steady, "drift") == PASS


def test_reference_check() -> None:
    src = simulated_selftest_source(noise=0.0005, seed=4)
    r = quiet(source=src, n=3, reference_check=True).report
    assert [x.sample_id for x in r.references] == ["REF-WHITE", "REF-GREY", "REF-BLACK"]
    assert r.references[0].L > r.references[1].L > r.references[2].L
    assert status(r, "lightness_order") == PASS and r.verdict == PASS
    # swapped grey/white references and a tinted grey
    src = simulated_selftest_source(noise=0.0005, seed=4)
    src.fixed["REF-WHITE"], src.fixed["REF-GREY"] = (
        src.fixed["REF-GREY"],
        src.fixed["REF-WHITE"].copy(),
    )
    src.fixed["REF-GREY"] = src.fixed["REF-GREY"] * np.where(WAVELENGTHS > 580, 1.0, 0.8)
    bad = quiet(source=src, n=3, reference_check=True).report
    assert status(bad, "lightness_order") == FAIL
    assert status(bad, "cast_REF-GREY") == WARN
    assert bad.verdict == FAIL


# --- implausible spectra --------------------------------------------------------------------


def _white() -> np.ndarray:
    return 0.88 - 0.06 * np.exp(-(WAVELENGTHS - 400.0) / 25.0)


def test_negative_values_fail() -> None:
    spectra = [_white() + 0.0005 * i for i in range(4)]
    spectra[2] = spectra[2].copy()
    spectra[2][0] = -0.01
    r = quiet(source=FileImportSource(text=tile_csv(spectra)), n=4).report
    assert status(r, "negative_values") == FAIL and r.verdict == FAIL


def test_implausible_white_and_jumps_fail() -> None:
    grey = [np.full(len(WAVELENGTHS), 0.3) for _ in range(3)]
    r = quiet(source=FileImportSource(text=tile_csv(grey)), n=3).report
    assert status(r, "white_range") == FAIL and "not a plausible white tile" in format_report(r)
    spiky = _white().copy()
    spiky[list(WAVELENGTHS).index(550)] += 0.08
    r = quiet(source=FileImportSource(text=tile_csv([spiky] * 3)), n=3).report
    assert status(r, "band_jumps") == FAIL and "540-550 nm" in format_report(r)
    rough = _white() + 0.012 * (-1) ** np.arange(len(WAVELENGTHS))
    s = analyse_tile(np.stack([rough] * 3), SelftestThresholds())[1]
    assert next(c for c in s if c.name == "smoothness").status == WARN
    with pytest.raises(ValueError):
        analyse_tile(np.stack([_white()] * 2), SelftestThresholds())


def test_recorded_spotread_spectrum_with_negative_value() -> None:
    text = (DATA / "session_colormunki.txt").read_text()
    white = parse_spotread_output(text)[0]
    assert (
        analyse_tile(np.stack([white.reading().reflectance] * 3), SelftestThresholds())[1][2].status
        == PASS
    )
    # same transcript with one corrupted band
    vals = list(white.values)
    vals[5] = -1.5
    corrupted = (
        "Spectrum from 380.000 to 730.000 nm in 36 steps\n"
        + ", ".join(f"{v:8.3f}" for v in vals)
        + "\n"
    )
    bad = parse_spotread_output(corrupted)[0].reading().reflectance
    checks = analyse_tile(
        np.stack([bad, white.reading().reflectance, white.reading().reflectance]),
        SelftestThresholds(),
    )[1]
    assert {c.name: c.status for c in checks}["negative_values"] == FAIL


# --- full CLI against the fake instrument ---------------------------------------------------


def test_cli_selftest_with_recorded_spotread_output(tmp_path: Path) -> None:
    env = {
        "FAKE_SPOTREAD_PORTS": "colormunki",
        "FAKE_SPOTREAD_BLOCK": "0",  # always replay the recorded white-tile reading
        "PAINTMIXER_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}",
    }
    res = CliRunner().invoke(
        app,
        ["measure", "selftest", "--spotread", FAKE, "--n", "3", "--out-dir", str(tmp_path)],
        env=env,
        input="\n" * 20,
    )
    assert res.exit_code == 0, res.output
    assert "Using port 1: X-Rite ColorMunki" in res.output and "Verdict: PASS" in res.output
    (out,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    report = json.loads((out / "report.json").read_text())
    assert report["instrument"] == "X-Rite ColorMunki" and report["source"] == "spotread"
    raw = list(csv.DictReader((out / "spectra_raw.csv").open()))
    assert len(raw) == 3 and "r380" in raw[0] and "r730" in raw[0]


def test_cli_exit_codes_and_threshold_overrides(tmp_path: Path) -> None:
    env = {"PAINTMIXER_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"}
    base = ["measure", "selftest", "--source", "simulated", "--out-dir", str(tmp_path)]
    ok = CliRunner().invoke(app, base, env=env, input="\n" * 30)
    assert ok.exit_code == 0, ok.output
    warn = CliRunner().invoke(app, [*base, "--warn-de", "0.01"], env=env, input="\n" * 30)
    assert warn.exit_code == 3 and "Verdict: WARN" in warn.output
    fail = CliRunner().invoke(app, [*base, "--sim-noise", "0.05"], env=env, input="\n" * 30)
    assert fail.exit_code == 1 and "Verdict: FAIL" in fail.output
    bad = CliRunner().invoke(app, [*base, "--warn-de", "2", "--fail-de", "1"], env=env)
    assert bad.exit_code != 0


# --- thresholds from settings ---------------------------------------------------------------


def test_thresholds_come_from_app_settings(tmp_path: Path) -> None:
    from paintmixer.api.app import create_app
    from paintmixer.config import Settings

    url = f"sqlite:///{tmp_path / 'app.db'}"
    assert selftest_thresholds(settings_from_db(url)) == SelftestThresholds()  # no DB yet
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as c:
        s = c.get("/api/v1/settings").json()
        assert (s["selftest_warn_de"], s["selftest_fail_de"]) == (0.5, 1.0)
        r = c.patch("/api/v1/settings", json={"selftest_warn_de": 2.0})
        assert r.status_code == 422  # warn must not exceed fail
        assert c.patch("/api/v1/settings", json={"selftest_warn_de": 0.01}).status_code == 200
    assert selftest_thresholds(settings_from_db(url)).warn_de == 0.01
    res = CliRunner().invoke(
        app,
        ["measure", "selftest", "--source", "simulated", "--out-dir", str(tmp_path)],
        env={"PAINTMIXER_DATABASE_URL": url},
        input="\n" * 30,
    )
    assert res.exit_code == 3 and "warn > 0.01" in res.output


def test_default_output_root(tmp_path: Path) -> None:
    (tmp_path / "sample_data").mkdir()
    (tmp_path / "backend").mkdir()
    assert default_output_root(tmp_path / "backend") == tmp_path / "sample_data" / "selftests"
    lone = tmp_path / "elsewhere"
    lone.mkdir()
    assert default_output_root(lone).name == "selftests"
