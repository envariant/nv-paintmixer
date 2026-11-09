"""Command-line entry point (``paintmixer``)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from paintmixer.measurement.sources import SimulatedSource

app = typer.Typer(help="PaintMixer command-line tools", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the package version."""
    from paintmixer import __version__

    typer.echo(__version__)


@app.command()
def synthetic(out: Path = typer.Option(Path("../sample_data"), help="Output directory")) -> None:
    """Regenerate the synthetic sample data (paints, calibration CSVs, ground truth)."""
    from paintmixer.calibration.synthetic import write_sample_data

    for p in write_sample_data(out):
        typer.echo(f"wrote {p}")


@app.command("seed-demo")
def seed_demo_cmd(
    refit: bool = typer.Option(False, help="Fit again and add new model versions"),
    sample_dir: Path | None = typer.Option(None, help="Default: the repository's sample_data/"),
) -> None:
    """Seed the database with the CMYKW demo: 5 paints, colour library, calibrated model."""
    from paintmixer.config import get_settings
    from paintmixer.demo import seed_demo

    url = get_settings().database_url
    report = seed_demo(url, sample_dir, refit=refit)
    typer.echo(f"Seeded {url}")
    typer.echo(report.summary())
    if report.errors:
        raise typer.Exit(1)


@app.command()
def schema(out: Path = typer.Option(..., help="Where to write the JSON schema")) -> None:
    """Write the calibration-row JSON schema."""
    from paintmixer.calibration.schema import schema_json

    out.write_text(schema_json())
    typer.echo(f"wrote {out}")


@app.command("parity-fixture")
def parity_fixture(
    out: Path | None = typer.Option(None, help="Default: frontend/src/lib/"),
) -> None:
    """Write the golden values the browser forward model is tested against."""
    from paintmixer.parity import FIXTURE, fixture_json

    path = out or FIXTURE
    path.write_text(fixture_json())
    typer.echo(f"wrote {path}")


@app.command()
def openapi(out: Path = typer.Option(Path("openapi.json"))) -> None:
    """Export the OpenAPI document."""
    from paintmixer.api.app import create_app

    out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
    typer.echo(f"wrote {out}")


@app.command()
def validate(
    csv_path: Path,
    paints_csv: Path | None = typer.Option(None, "--paints", help="paints.csv for id checks"),
) -> None:
    """Validate a calibration CSV and print row/column-precise issues."""
    from paintmixer.calibration.format import parse_calibration_csv

    paints = _read_paints(paints_csv) if paints_csv is not None else None
    report = parse_calibration_csv(csv_path.read_text(), paints)
    for i in report.issues:
        loc = f"line {i.row}" if i.row else "file"
        if i.column:
            loc += f", column {i.column}"
        typer.echo(f"{i.severity.upper():7} {loc}: [{i.code}] {i.message}")
    typer.echo(
        f"{len(report.samples)} valid samples of {report.n_rows} rows; "
        f"{len(report.errors)} errors, {len(report.warnings)} warnings"
    )
    raise typer.Exit(code=0 if report.ok else 1)


def _read_paints(paints_csv: Path):  # type: ignore[no-untyped-def]
    import csv

    from paintmixer.domain import PaintInfo, PaintRole

    with paints_csv.open() as fh:
        return {
            r["id"]: PaintInfo(
                r["id"],
                PaintRole(r["role"]),
                float(r["density_g_per_ml"]),
                name=r.get("name", ""),
                cost_per_ml=float(r.get("cost_per_ml") or 0),
                min_dose_ml=float(r.get("min_dose_ml") or 0),
            )
            for r in csv.DictReader(fh)
        }


@app.command()
def fit(
    csv_path: Path,
    paints_csv: Path = typer.Option(..., "--paints", help="paints.csv"),
    out: Path | None = typer.Option(None, help="Write the fitted model as JSON"),
    k2: float = typer.Option(0.5, help="Saunderson internal reflection k2"),
    k1: float = typer.Option(0.0, help="Saunderson external reflection k1"),
) -> None:
    """Fit K/S from a calibration CSV and print the report."""
    from paintmixer.calibration.fit import FitOptions, fit_calibration
    from paintmixer.calibration.format import parse_calibration_csv
    from paintmixer.calibration.report import fit_result_to_dict, fit_summary_text

    paints = _read_paints(paints_csv)
    report = parse_calibration_csv(csv_path.read_text(), paints)
    if not report.ok:
        for i in report.errors[:20]:
            typer.echo(f"ERROR line {i.row}, {i.column}: {i.message}", err=True)
        raise typer.Exit(1)
    result = fit_calibration(report.samples, paints, FitOptions(k1=k1, k2=k2))
    typer.echo(fit_summary_text(result))
    if out is not None:
        out.write_text(json.dumps(fit_result_to_dict(result), indent=1) + "\n")
        typer.echo(f"wrote {out}")


measure_app = typer.Typer(help="Measurement tools", no_args_is_help=True)
app.add_typer(measure_app, name="measure")


@measure_app.command("session")
def measure_session(
    worksheet: Path = typer.Option(..., help="Worksheet CSV skeleton (POST /worksheet/csv)"),
    out: Path = typer.Option(..., help="Calibration CSV to write/append (resumable)"),
    source: str = typer.Option("spotread", help="spotread | simulated | file"),
    file: Path | None = typer.Option(None, help="Spectra CSV for --source file"),
    readings: int = typer.Option(3, min=1, help="Readings per sample"),
    max_de: float = typer.Option(0.5, help="Warn when repeat readings differ by more (dE2000)"),
    ask_masses: bool = typer.Option(False, help="Prompt for actual weighed masses per drawdown"),
    spotread: str = typer.Option("spotread", help="spotread executable"),
    seed: int = typer.Option(0, help="Seed for the simulated source"),
) -> None:
    """Walk the worksheet, prompting the operator for each sample and background."""
    from paintmixer.measurement.base import MeasurementSource
    from paintmixer.measurement.session import MeasureSession, load_worksheet_csv
    from paintmixer.measurement.sources import FileImportSource, SimulatedSource
    from paintmixer.measurement.spotread import ArgyllSpotread

    samples = load_worksheet_csv(worksheet.read_text())
    src: MeasurementSource
    if source == "spotread":

        def operator(msg: str) -> None:
            typer.prompt(msg + " [Enter]", default="", show_default=False)

        src = ArgyllSpotread(spotread, prompt=operator)
    elif source == "file":
        if file is None:
            raise typer.BadParameter("--file is required with --source file")
        src = FileImportSource(file)
    elif source == "simulated":
        from paintmixer.calibration.synthetic import (
            POOL_IDS,
            SyntheticTruth,
            synthetic_paints,
            true_tau,
        )

        ids = sorted({p for s in samples for p in s.components_dict})
        known = [i for i in POOL_IDS if i in ids]
        truth = SyntheticTruth(synthetic_paints(known), true_tau(), 0.0, 0.5)
        src = SimulatedSource(truth.model, truth.ids, seed=seed)
    else:
        raise typer.BadParameter("source must be spotread, simulated or file")
    session = MeasureSession(
        samples,
        src,
        out,
        readings=readings,
        max_de=max_de,
        ask=lambda msg: typer.prompt(msg, default="", show_default=False),
        say=typer.echo,
        ask_masses=ask_masses,
    )
    summary = session.run()
    typer.echo(
        f"measured {len(summary.measured)}, skipped {len(summary.skipped)}, "
        f"previously done {summary.already_done}; {len(summary.warnings)} repeatability warnings"
    )


SELFTEST_EXIT = {"PASS": 0, "FAIL": 1, "WARN": 3}
NO_INSTRUMENT_EXIT = 2


@measure_app.command("selftest")
def measure_selftest(
    n: int = typer.Option(10, "--n", min=3, help="Readings of the white tile"),
    replace: bool = typer.Option(False, help="Lift and replace the instrument between readings"),
    reference_check: bool = typer.Option(
        False, help="Also read matte white, mid-grey and matte black references"
    ),
    reference_readings: int = typer.Option(3, min=1, help="Readings per reference"),
    source: str = typer.Option("spotread", help="spotread | simulated | file"),
    file: Path | None = typer.Option(None, help="Spectra CSV for --source file"),
    spotread: str = typer.Option("spotread", help="spotread executable"),
    port: int | None = typer.Option(None, help="spotread -c port number (default: first)"),
    detect_timeout: float = typer.Option(30.0, help="Seconds to wait for `spotread -?`"),
    out_dir: Path | None = typer.Option(
        None, help="Output root (default <repo>/sample_data/selftests)"
    ),
    warn_de: float | None = typer.Option(None, help="Override the WARN threshold (dE2000)"),
    fail_de: float | None = typer.Option(None, help="Override the FAIL threshold (dE2000)"),
    sim_noise: float = typer.Option(0.001, help="Simulated source: reflectance noise sigma"),
    sim_drift: float = typer.Option(0.0, help="Simulated source: relative drift per reading"),
    seed: int = typer.Option(0, help="Simulated source: seed"),
) -> None:
    """Check an instrument: detection, white calibration, repeatability, drift, sanity.

    Exit codes: 0 PASS, 3 WARN, 1 FAIL, 2 instrument not found / setup error.
    """
    import dataclasses

    from paintmixer.api.services import selftest_thresholds, settings_from_db
    from paintmixer.config import get_settings
    from paintmixer.measurement.base import MeasurementError, MeasurementSource
    from paintmixer.measurement.selftest import (
        default_output_root,
        format_report,
        run_selftest,
        write_outputs,
    )
    from paintmixer.measurement.sources import FileImportSource
    from paintmixer.measurement.spotread import ArgyllSpotread, detect_instruments

    thresholds = selftest_thresholds(settings_from_db(get_settings().database_url))
    if warn_de is not None:
        thresholds = dataclasses.replace(thresholds, warn_de=warn_de)
    if fail_de is not None:
        thresholds = dataclasses.replace(thresholds, fail_de=fail_de)
    if thresholds.warn_de > thresholds.fail_de:
        raise typer.BadParameter("warn threshold must be <= fail threshold")

    def ask(msg: str) -> str:
        return str(typer.prompt(msg, default="", show_default=False))

    instrument: str | None = None
    src: MeasurementSource
    if source == "spotread":
        typer.echo(f"Detecting instruments (`{spotread} -?`)...")
        det = detect_instruments(spotread, detect_timeout)
        if not det.instruments:
            typer.echo(no_instrument_help(det.error, det.timed_out, det.ports), err=True)
            raise typer.Exit(NO_INSTRUMENT_EXIT)
        for p in det.ports:
            mark = " (disabled: no firmware)" if p.disabled else ""
            typer.echo(f"  port {p.index}: {p.name}{mark}")
        chosen = next((p for p in det.instruments if port is None or p.index == port), None)
        if chosen is None:
            typer.echo(f"No usable instrument on port {port}.", err=True)
            raise typer.Exit(NO_INSTRUMENT_EXIT)
        instrument = chosen.instrument
        typer.echo(f"Using port {chosen.index}: {instrument}")

        def operator(msg: str) -> None:
            ask(msg + " [Enter]")

        src = ArgyllSpotread(spotread, ("-c", str(chosen.index)), prompt=operator)
    elif source == "file":
        if file is None:
            raise typer.BadParameter("--file is required with --source file")
        src = FileImportSource(file)
    elif source == "simulated":
        src = simulated_selftest_source(noise=sim_noise, drift=sim_drift, seed=seed)
    else:
        raise typer.BadParameter("source must be spotread, simulated or file")

    try:
        run = run_selftest(
            src,
            n=n,
            replace=replace,
            reference_check=reference_check,
            reference_readings=reference_readings,
            thresholds=thresholds,
            ask=ask,
            say=typer.echo,
            instrument=instrument,
        )
    except MeasurementError as e:
        typer.echo(f"Measurement failed: {e}", err=True)
        raise typer.Exit(NO_INSTRUMENT_EXIT) from e
    typer.echo("")
    typer.echo(format_report(run.report))
    out = write_outputs(run, out_dir or default_output_root())
    typer.echo(f"\nReport and spectra written to {out}")
    raise typer.Exit(SELFTEST_EXIT[run.report.verdict])


def no_instrument_help(error: str | None, timed_out: bool, ports: Sequence[object]) -> str:
    lines = ["No spectrophotometer found by ArgyllCMS spotread."]
    if error:
        lines.append(f"  ({error})")
    elif timed_out:
        lines.append("  (spotread did not finish listing ports before the timeout)")
    elif ports:
        lines.append("  (only serial ports or instruments without firmware were listed)")
    lines += [
        "",
        "On macOS, check in this order:",
        "  1. ArgyllCMS is installed and on PATH:  brew install argyll-cms  (then: which spotread)",
        "  2. Try another USB port or cable; connect directly rather than through a hub.",
        "  3. Old X-Rite software can hold the device: quit X-Rite / i1Profiler / ColorMunki apps",
        "     and check for X-Rite background daemons (ps aux | grep -i xrite; launch daemons in",
        "     /Library/LaunchDaemons). Unload or remove them, or reboot after uninstalling.",
        "  4. Try with elevated USB permissions:  sudo spotread -?",
        "  5. Run `spotread -?` yourself: the instrument must appear in the -c port list.",
        "Then re-run: paintmixer measure selftest",
    ]
    return "\n".join(lines)


def simulated_selftest_source(
    noise: float = 0.001, drift: float = 0.0, seed: int = 0
) -> SimulatedSource:
    """Simulated instrument with a ceramic-white-like tile and neutral references."""
    import numpy as np

    from paintmixer.calibration.synthetic import STARTER_IDS, synthetic_paints
    from paintmixer.colorsci.km import KMModel
    from paintmixer.colorsci.spectral import N_BANDS, WAVELENGTHS
    from paintmixer.measurement.sources import SimulatedSource

    ps = synthetic_paints(STARTER_IDS)
    km = KMModel(np.stack([p.K for p in ps]), np.stack([p.S for p in ps]))
    tile = 0.88 - 0.06 * np.exp(-(WAVELENGTHS - 400.0) / 25.0)
    fixed = {
        "WHITE-TILE": tile,
        "REF-WHITE": np.full(N_BANDS, 0.86),
        "REF-GREY": np.full(N_BANDS, 0.19),
        "REF-BLACK": np.full(N_BANDS, 0.03),
    }
    return SimulatedSource(
        km, [p.info.id for p in ps], noise=noise, drift_per_read=drift, seed=seed, fixed=fixed
    )


def main() -> None:
    app()
