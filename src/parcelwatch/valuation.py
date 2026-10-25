"""F9: value per sq ft and estimated missed tax (milestone M7)."""

from __future__ import annotations

import geopandas as gpd

from parcelwatch.config import Config


def value_per_sqft(parcels: gpd.GeoDataFrame, cfg: Config) -> float:
    """Median ``BLDG_VAL / HEATEDAREA`` for recent builds, per TRD section 3.1.

    Falls back to all of Wake County when the box has fewer than the minimum sample.

    Args:
        parcels: Parcels with building value, heated area and year built.
        cfg: Loaded config (``valuation`` filters).

    Returns:
        Dollars per heated sq ft.
    """
    raise NotImplementedError("M7")


def estimate_missed_tax(
    parcel_changes: gpd.GeoDataFrame, precision: float, cfg: Config, vpsf: float
) -> tuple[gpd.GeoDataFrame, dict[str, float]]:
    """Estimate missed value and yearly tax per parcel, plus precision-adjusted totals.

    Args:
        parcel_changes: Parcel change table with ``added_sqft`` and ``city``.
        precision: Measured precision from ``metrics.json``.
        cfg: Loaded config (rates, assessment ratio).
        vpsf: Value per sq ft from :func:`value_per_sqft`.

    Returns:
        ``(parcel_changes_with_money, totals)``.
    """
    raise NotImplementedError("M7")
