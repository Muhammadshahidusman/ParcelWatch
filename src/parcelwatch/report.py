"""The ``report`` step: dollars, H3 export and figures (milestone M7)."""

from __future__ import annotations

from parcelwatch.config import Config


def run(cfg: Config, *, force: bool = False) -> None:
    """Compute value per sq ft and missed tax, export public H3 tiles and stats, draw figures."""
    raise NotImplementedError("M7")
