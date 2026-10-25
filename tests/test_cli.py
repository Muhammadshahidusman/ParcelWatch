"""The CLI exposes the six pipeline commands and fails cleanly on unbuilt steps."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from parcelwatch import __version__
from parcelwatch.cli import app

runner = CliRunner()
COMMANDS = ("download", "prepare", "detect", "changes", "validate", "report")


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in COMMANDS:
        assert cmd in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_validate_needs_exactly_one_mode(tmp_project: Path) -> None:
    cfg = str(tmp_project / "configs" / "wake_pilot.yaml")
    assert runner.invoke(app, ["validate", "--config", cfg]).exit_code == 2
    both = runner.invoke(app, ["validate", "--config", cfg, "--make-sheet", "--score"])
    assert both.exit_code == 2


def test_detect_rejects_unknown_model(tmp_project: Path) -> None:
    cfg = str(tmp_project / "configs" / "wake_pilot.yaml")
    assert runner.invoke(app, ["detect", "--config", cfg, "--model", "v9"]).exit_code != 0


def test_missing_config_fails() -> None:
    assert runner.invoke(app, ["download", "--config", "nope.yaml"]).exit_code != 0


def test_unbuilt_step_exits_nonzero_and_writes_log(tmp_project: Path) -> None:
    cfg = str(tmp_project / "configs" / "wake_pilot.yaml")
    result = runner.invoke(app, ["report", "--config", cfg])
    assert result.exit_code == 2
    logs = list((tmp_project / "results" / "logs").glob("report_*.log"))
    assert len(logs) == 1
    assert "not implemented yet" in logs[0].read_text("utf-8")
