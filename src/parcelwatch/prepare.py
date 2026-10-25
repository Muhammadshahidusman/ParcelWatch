"""F2: mosaic, align, clip and measure the Before/After offset (milestone M2)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from parcelwatch.config import Config


def mosaic(folder: Path, out: Path, cfg: Config) -> Path:
    """Mosaic one year's NAIP tiles, reproject to the working CRS and clip to the box.

    Args:
        folder: Folder of raw tiles for one year.
        out: Output GeoTIFF under ``data/processed/``.
        cfg: Loaded config (box, CRS, GSD).

    Returns:
        ``out``.
    """
    raise NotImplementedError("M2")


def align_to(reference: Path, target: Path, out: Path) -> Path:
    """Resample ``target`` onto the exact grid (CRS, transform, shape) of ``reference``.

    Args:
        reference: Before mosaic.
        target: After mosaic.
        out: Aligned After GeoTIFF.

    Returns:
        ``out``.
    """
    raise NotImplementedError("M2")


def clip_vectors(cfg: Config) -> dict[str, Path]:
    """Clip every raw vector layer to the box in the working CRS.

    Args:
        cfg: Loaded config.

    Returns:
        Map of layer name to clipped file path.
    """
    raise NotImplementedError("M2")


def measure_offset(before: Path, after: Path, points: gpd.GeoDataFrame) -> dict[str, float]:
    """Summarize owner-measured offsets at road intersections and derive the match tolerance.

    Args:
        before: Before mosaic.
        after: Aligned After mosaic.
        points: Paired points (before/after positions) measured by the owner.

    Returns:
        ``{"max_offset_m": ..., "match_tolerance_m": ...}`` per the config tolerance rule.
    """
    raise NotImplementedError("M2")


def run(cfg: Config, *, force: bool = False) -> None:
    """Run every F2 preparation step for the config."""
    raise NotImplementedError("M2")
