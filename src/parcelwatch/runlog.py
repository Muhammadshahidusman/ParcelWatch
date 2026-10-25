"""Run logging and the run manifest (TRD sections 6 and 11)."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parcelwatch.config import Config

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(command: str, log_dir: Path, level: int = logging.INFO) -> Path:
    """Log to the console and to ``{log_dir}/{command}_{timestamp}.log``.

    Args:
        command: CLI command name, used in the log file name.
        log_dir: Folder for log files, created if missing.
        level: Logging level, INFO by default.

    Returns:
        Path of the log file.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_file = log_dir / f"{command}_{stamp}.log"
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(LOG_FORMAT)
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8"),
    ):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    return log_file


def git_commit(root: Path) -> str | None:
    """Return the current git commit hash of ``root``, or None outside a repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def update_manifest(
    path: Path, cfg: Config, step: str, extra: dict[str, Any] | None = None
) -> None:
    """Merge one step's record into ``results/run_manifest.json``.

    Args:
        path: Manifest file path.
        cfg: Loaded config (its hash and NAIP item IDs are recorded).
        step: Pipeline step name.
        extra: Step-specific values such as counts or the model version.
    """
    manifest: dict[str, Any] = json.loads(path.read_text("utf-8")) if path.exists() else {}
    manifest.update(
        {
            "config_sha256": cfg.sha256,
            "git_commit": git_commit(cfg.root),
            "naip": {
                k: {"date": str(d.date), "items": d.items}
                for k, d in (
                    ("before", cfg.imagery.before),
                    ("after", cfg.imagery.after),
                )
            },
        }
    )
    steps = manifest.setdefault("steps", {})
    steps[step] = {"finished_at": datetime.now(UTC).isoformat(), **(extra or {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, default=str), "utf-8")
