"""Command-line entry point (``paintmixer``)."""

from __future__ import annotations

import typer

app = typer.Typer(help="PaintMixer command-line tools", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the package version."""
    from paintmixer import __version__

    typer.echo(__version__)


def main() -> None:
    app()
