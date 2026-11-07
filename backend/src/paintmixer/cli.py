"""Command-line entry point (``paintmixer``)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

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


@app.command()
def schema(out: Path = typer.Option(..., help="Where to write the JSON schema")) -> None:
    """Write the calibration-row JSON schema."""
    from paintmixer.calibration.schema import schema_json

    out.write_text(schema_json())
    typer.echo(f"wrote {out}")


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


def main() -> None:
    app()
