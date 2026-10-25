"""Python API mirroring the CLI: ``pipeline.run(config_path, steps=[...])`` (TRD section 6)."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path

from parcelwatch import changes, detect, download, prepare, report, validate
from parcelwatch.config import Config, load_config
from parcelwatch.paths import Paths
from parcelwatch.runlog import update_manifest

log = logging.getLogger(__name__)

STEPS: tuple[str, ...] = ("download", "prepare", "detect", "changes", "validate", "report")


def run_step(
    cfg: Config,
    step: str,
    *,
    model: str = "v0",
    force: bool = False,
    train: bool = False,
    make_sheet: bool = False,
    score: bool = False,
) -> None:
    """Run one pipeline step, time it and record it in the run manifest.

    Args:
        cfg: Loaded config.
        step: One of :data:`STEPS`.
        model: ``v0`` or ``v1`` for ``detect`` and ``changes``.
        force: Redo work whose outputs already exist.
        train: For ``detect``, also build v1 training tiles.
        make_sheet: For ``validate``, draw the sample sheet.
        score: For ``validate``, score the labeled sheet.

    Raises:
        ValueError: If ``step`` is unknown.
    """
    t0 = time.perf_counter()
    log.info("step %s started (model=%s, force=%s)", step, model, force)
    if step == "download":
        download.run(cfg, force=force)
    elif step == "prepare":
        prepare.run(cfg, force=force)
    elif step == "detect":
        detect.run(cfg, model, train=train, force=force)
    elif step == "changes":
        changes.run(cfg, model, force=force)
    elif step == "validate":
        validate.run(cfg, make_sheet=make_sheet, score=score, force=force)
    elif step == "report":
        report.run(cfg, force=force)
    else:
        raise ValueError(f"unknown step {step!r}, expected one of {STEPS}")
    seconds = round(time.perf_counter() - t0, 1)
    log.info("step %s finished in %.1f s", step, seconds)
    update_manifest(Paths(cfg.root).run_manifest, cfg, step, {"model": model, "seconds": seconds})


def run(config_path: str | Path, steps: Sequence[str] = STEPS, *, model: str = "v0") -> None:
    """Run several steps in order from one config file.

    Args:
        config_path: Path to the YAML config.
        steps: Step names, in order.
        model: ``v0`` or ``v1``.
    """
    cfg = load_config(config_path)
    for step in steps:
        run_step(cfg, step, model=model)
