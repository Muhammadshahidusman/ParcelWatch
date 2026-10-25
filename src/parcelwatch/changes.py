"""F5/F6/F7: object-based change classification, parcel roll-up and permit check (M4)."""

from __future__ import annotations

from datetime import date

import geopandas as gpd

from parcelwatch.config import Config


def classify_changes(
    before: gpd.GeoDataFrame, after: gpd.GeoDataFrame, cfg: Config, tolerance_m: float
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Label After buildings new/expanded/unchanged and find demolished Before buildings.

    Implements TRD section 3.1 exactly. All geometry must be in the working CRS.

    Args:
        before: Before building polygons.
        after: After building polygons.
        cfg: Loaded config (``change`` thresholds).
        tolerance_m: Match buffer in meters, from ``results/alignment_report.json``.

    Returns:
        ``(after_labeled, demolished)``.
    """
    raise NotImplementedError("M4")


def rollup_to_parcels(changes: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Assign each changed building to one parcel by representative point and aggregate.

    Args:
        changes: Labeled buildings (new, expanded, demolished).
        parcels: Parcels in the working CRS.

    Returns:
        One row per changed parcel with counts and added area.
    """
    raise NotImplementedError("M4")


def attach_permits(
    parcel_changes: gpd.GeoDataFrame,
    permits: gpd.GeoDataFrame,
    window: tuple[date, date],
    cfg: Config,
) -> gpd.GeoDataFrame:
    """Count permits per parcel (spatial within or PIN match) and set ``flag_unpermitted``.

    Args:
        parcel_changes: Output of :func:`rollup_to_parcels`.
        permits: Permit points in the working CRS.
        window: Inclusive (start, end) permit window.
        cfg: Loaded config (counting types, field names).

    Returns:
        ``parcel_changes`` with ``n_permits`` and ``flag_unpermitted``.
    """
    raise NotImplementedError("M4")


def run(cfg: Config, model: str, *, force: bool = False) -> None:
    """Run classification, roll-up and permit check for the chosen model."""
    raise NotImplementedError("M4")
