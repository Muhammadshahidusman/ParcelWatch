"""F9: value per sq ft and estimated missed tax (milestone M7)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import geopandas as gpd
import pandas as pd

from parcelwatch.config import Config


@dataclass(frozen=True)
class ValuePerSqft:
    """Median building value per heated sq ft and how it was computed."""

    value: float
    n: int
    scope: str  # "bbox" or "county"
    min_year_built: int

    def to_dict(self) -> dict[str, float | int | str]:
        """Plain dict for JSON."""
        return asdict(self)


def _recent_ratio(parcels: pd.DataFrame, cfg: Config) -> pd.Series:
    """``BLDG_VAL / HEATEDAREA`` for parcels passing the recent-build filters."""
    f, v = cfg.fields, cfg.valuation
    min_year = v.tax_year - v.recent_build_years
    bv = pd.to_numeric(parcels[f.building_value], errors="coerce")
    ha = pd.to_numeric(parcels[f.heated_area_sqft], errors="coerce")
    yb = pd.to_numeric(parcels[f.year_built], errors="coerce")
    ok = (
        (yb >= min_year)
        & (ha >= v.value_per_sqft_filters.min_heated_sqft)
        & (bv >= v.value_per_sqft_filters.min_building_value)
    )
    return (bv[ok] / ha[ok]).dropna()


def value_per_sqft(
    parcels: pd.DataFrame, cfg: Config, county: pd.DataFrame | None = None
) -> ValuePerSqft:
    """Median ``BLDG_VAL / HEATEDAREA`` for recent builds, per TRD section 3.1.

    Recent means ``YEAR_BUILT >= tax_year - recent_build_years`` (2021 for tax year 2026),
    with ``HEATEDAREA >= 600`` and ``BLDG_VAL > 0``. Uses parcels in the box; falls back to
    all of Wake County when fewer than ``value_per_sqft_min_sample`` qualify.

    Args:
        parcels: Box parcels (rows with ``in_box`` False are ignored if the column exists).
        cfg: Loaded config (``valuation`` filters).
        county: All county parcels, used only for the fallback.

    Returns:
        :class:`ValuePerSqft`.

    Raises:
        ValueError: If the box sample is too small and no county table is given.
    """
    v = cfg.valuation
    min_year = v.tax_year - v.recent_build_years
    box_rows = parcels[parcels["in_box"]] if "in_box" in parcels else parcels
    ratio = _recent_ratio(box_rows, cfg)
    if len(ratio) >= v.value_per_sqft_min_sample:
        return ValuePerSqft(float(ratio.median()), len(ratio), "bbox", min_year)
    if county is None:
        raise ValueError(
            f"fewer than {v.value_per_sqft_min_sample} recent builds in the box "
            f"({len(ratio)}); pass the county parcels for the fallback"
        )
    ratio = _recent_ratio(county, cfg)
    return ValuePerSqft(float(ratio.median()), len(ratio), "county", min_year)


def estimate_missed_tax(
    parcel_changes: gpd.GeoDataFrame, precision: float | None, cfg: Config, vpsf: float
) -> tuple[gpd.GeoDataFrame, dict[str, float | None]]:
    """Estimate missed value and yearly tax per parcel, plus precision-adjusted totals.

    ``missed_value = added_sqft × value_per_sqft × assessment_ratio``;
    ``yearly_tax = missed_value × (county + town rate in cents per $100) / 100 / 100``.
    Fire tax is excluded. Totals cover flagged parcels only and the headline figure is
    multiplied by measured precision (None until validation is scored).

    Args:
        parcel_changes: Parcel change table with ``added_sqft``, ``city``, ``flag_unpermitted``.
        precision: Measured precision from ``metrics.json``, or None.
        cfg: Loaded config (rates, assessment ratio).
        vpsf: Value per sq ft.

    Returns:
        ``(parcel_changes_with_money, totals)``.
    """
    v = cfg.valuation
    out = parcel_changes.copy()
    out["value_per_sqft"] = vpsf
    out["est_missed_value_usd"] = out["added_sqft"] * vpsf * v.assessment_ratio
    rate = v.county_rate_cents_per_100 + out["city"].map(v.municipal_rate)
    out["est_yearly_tax_usd"] = out["est_missed_value_usd"] * rate / 100 / 100
    flagged = out["flag_unpermitted"].astype(bool)
    ranks = out.loc[flagged, "est_yearly_tax_usd"].rank(method="first", ascending=False)
    out["rank"] = ranks.reindex(out.index).astype("Int64")
    raw_tax = float(out.loc[flagged, "est_yearly_tax_usd"].sum())
    raw_value = float(out.loc[flagged, "est_missed_value_usd"].sum())
    totals: dict[str, float | None] = {
        "n_flagged": int(flagged.sum()),
        "added_sqft_flagged": float(out.loc[flagged, "added_sqft"].sum()),
        "value_per_sqft": vpsf,
        "precision": precision,
        "est_missed_value_usd_raw": raw_value,
        "est_yearly_tax_usd_raw": raw_tax,
        "est_missed_value_usd_adjusted": None if precision is None else raw_value * precision,
        "est_yearly_tax_usd_adjusted": None if precision is None else raw_tax * precision,
    }
    return out, totals
