"""``parcelwatch`` command-line interface (TRD section 6)."""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path

import typer

from parcelwatch import __version__
from parcelwatch.config import Config, load_config
from parcelwatch.paths import Paths
from parcelwatch.pipeline import run_step
from parcelwatch.runlog import setup_logging

app = typer.Typer(
    help="ParcelWatch: find buildings the tax roll missed.",
    no_args_is_help=True,
    add_completion=False,
)
log = logging.getLogger("parcelwatch")

ConfigOpt = typer.Option(..., "--config", "-c", exists=True, dir_okay=False, help="YAML config.")
ForceOpt = typer.Option(False, "--force", help="Redo work whose outputs already exist.")


class Model(StrEnum):
    """Detection model version."""

    v0 = "v0"
    v1 = "v1"


def _start(command: str, config: Path) -> Config:
    """Load the config and start logging for one command."""
    cfg = load_config(config)
    log_file = setup_logging(command, Paths(cfg.root).logs)
    log.info(
        "parcelwatch %s %s, config %s (sha256 %s)",
        __version__,
        command,
        config,
        cfg.sha256,
    )
    log.info("logging to %s", log_file)
    return cfg


def _execute(command: str, config: Path, **kwargs: object) -> None:
    """Run one step and turn failures into a non-zero exit code."""
    cfg = _start(command, config)
    try:
        run_step(cfg, command, **kwargs)  # type: ignore[arg-type]
    except NotImplementedError as exc:
        log.error("%s is not implemented yet (milestone %s)", command, exc)
        raise typer.Exit(code=2) from exc
    except Exception:
        log.exception("%s failed", command)
        raise typer.Exit(code=1) from None


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(False, "--version", help="Print the version and exit."),
) -> None:
    """ParcelWatch: find buildings the tax roll missed."""
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def download(config: Path = ConfigOpt, force: bool = ForceOpt) -> None:
    """Download NAIP, parcels, permits, town limits and Overture buildings."""
    _execute("download", config, force=force)


@app.command()
def prepare(config: Path = ConfigOpt, force: bool = ForceOpt) -> None:
    """Mosaic, align, clip and measure the image offset."""
    _execute("prepare", config, force=force)


@app.command()
def detect(
    config: Path = ConfigOpt,
    model: Model = typer.Option(Model.v0, "--model", help="Detection model."),
    train: bool = typer.Option(False, "--train", help="Also build v1 training tiles."),
    force: bool = ForceOpt,
) -> None:
    """Detect buildings on both years with the same model and settings."""
    _execute("detect", config, model=model.value, train=train, force=force)


@app.command()
def changes(
    config: Path = ConfigOpt,
    model: Model = typer.Option(Model.v0, "--model", help="Detection model."),
    force: bool = ForceOpt,
) -> None:
    """Classify changes, roll up to parcels and check permits."""
    _execute("changes", config, model=model.value, force=force)


@app.command()
def validate(
    config: Path = ConfigOpt,
    make_sheet: bool = typer.Option(False, "--make-sheet", help="Draw the 200-parcel sheet."),
    score: bool = typer.Option(False, "--score", help="Score the hand-labeled sheet."),
    force: bool = ForceOpt,
) -> None:
    """Make the validation sample sheet, or score it after hand labeling."""
    if make_sheet == score:
        typer.echo("Pass exactly one of --make-sheet or --score.", err=True)
        raise typer.Exit(code=2)
    _execute("validate", config, make_sheet=make_sheet, score=score, force=force)


@app.command()
def report(config: Path = ConfigOpt, force: bool = ForceOpt) -> None:
    """Estimate missed tax, export public H3 tiles and stats, draw figures."""
    _execute("report", config, force=force)


if __name__ == "__main__":  # pragma: no cover
    app()
