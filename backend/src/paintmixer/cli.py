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
    from paintmixer.domain import PaintInfo, PaintRole

    paints = None
    if paints_csv is not None:
        import csv

        with paints_csv.open() as fh:
            paints = {
                r["id"]: PaintInfo(r["id"], PaintRole(r["role"]), float(r["density_g_per_ml"]))
                for r in csv.DictReader(fh)
            }
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


def main() -> None:
    app()
