"""The ``report`` step: dollars, H3 export, stats, figures and the private review table (M7)."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from parcelwatch.config import Config
from parcelwatch.download import _vsizip
from parcelwatch.paths import Paths
from parcelwatch.publish import (
    audit_public_outputs,
    export_pmtiles,
    quantile_breaks,
    to_h3,
    write_stats,
)
from parcelwatch.validate import model_in_use
from parcelwatch.valuation import estimate_missed_tax, value_per_sqft

log = logging.getLogger(__name__)


def _county_value_table(cfg: Config) -> pd.DataFrame:
    """Read only the value fields for all county parcels (fallback for value per sq ft)."""
    f = cfg.fields
    p = Paths(cfg.root)
    cols = [f.building_value, f.heated_area_sqft, f.year_built]
    src = _vsizip(p.parcels_zip)
    have = pyogrio.read_info(src)["fields"]
    # Shapefile names are cut to 10 characters.
    use = [c if c in have else c[:10] for c in cols]
    df = pyogrio.read_dataframe(src, columns=use, read_geometry=False)
    return df.rename(columns=dict(zip(use, cols, strict=True)))


def _load_metrics(cfg: Config) -> dict[str, Any] | None:
    path = Paths(cfg.root).metrics
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def all_parcels_with_changes(
    parcels: gpd.GeoDataFrame, pc: gpd.GeoDataFrame, cfg: Config
) -> gpd.GeoDataFrame:
    """Every box parcel with ``changed``, ``flag_unpermitted`` and ``added_sqft`` columns."""
    pid = cfg.fields.parcel_id
    box_p = parcels[parcels["in_box"]]
    base = gpd.GeoDataFrame(
        {"parcel_id": box_p[pid].astype(str).to_numpy()},
        geometry=box_p.geometry.to_numpy(),
        crs=parcels.crs,
    )
    info = pc[["parcel_id", "flag_unpermitted", "added_sqft"]].drop_duplicates("parcel_id")
    out = base.merge(info, on="parcel_id", how="left")
    out["changed"] = out["flag_unpermitted"].notna()
    out["flag_unpermitted"] = out["flag_unpermitted"].fillna(False).astype(bool)
    out["added_sqft"] = out["added_sqft"].fillna(0.0)
    return out


def build_stats(
    cfg: Config,
    pc: gpd.GeoDataFrame,
    totals: dict[str, Any],
    metrics: dict[str, Any] | None,
    hexes: gpd.GeoDataFrame,
    model: str,
) -> dict[str, Any]:
    """Assemble ``stats.json`` (TRD section 4) plus hex breaks and validation status."""
    flagged = pc[pc["flag_unpermitted"].astype(bool)]
    precision = metrics["precision"] if metrics else None
    return {
        "area_km2": cfg.aoi.area_km2,
        "before_year": cfg.imagery.before.year,
        "after_year": cfg.imagery.after.year,
        "n_new": int(flagged["n_new"].sum()),
        "n_expanded": int(flagged["n_expanded"].sum()),
        "n_demolished": int(flagged["n_demolished"].sum()),
        "n_flagged": len(flagged),
        "n_changed": len(pc),
        "added_sqft_flagged": round(float(flagged["added_sqft"].sum()), -2),
        "precision": precision,
        "miss_rate": metrics["miss_rate"] if metrics else None,
        "validation_n_flagged": (metrics["tp"] + metrics["fp"]) if metrics else None,
        "validation_tp": metrics["tp"] if metrics else None,
        "validation_status": (metrics.get("labeled_by", "owner") if metrics else "pending"),
        "false_alarm_causes": metrics["false_alarm_causes"] if metrics else {},
        "confusion": {k: metrics[k] for k in ("tp", "fp", "fn", "tn")} if metrics else None,
        "est_yearly_tax_usd_adjusted": (
            round(totals["est_yearly_tax_usd_adjusted"], -2)
            if totals["est_yearly_tax_usd_adjusted"] is not None
            else None
        ),
        "value_per_sqft": round(float(totals["value_per_sqft"]), 2),
        "tax_year": cfg.valuation.tax_year,
        "model": model,
        "hex_breaks": quantile_breaks(hexes["n_flagged"].astype(float)),
        "naip_items": {
            "before": cfg.imagery.before.items,
            "after": cfg.imagery.after.items,
        },
        "bbox": list(cfg.aoi.bbox_wgs84),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def run(cfg: Config, *, force: bool = False) -> None:
    """Compute value per sq ft and missed tax, export public H3 tiles and stats, draw figures."""
    from parcelwatch.figures import make_figures
    from parcelwatch.review import write_review_table

    p = Paths(cfg.root)
    model = model_in_use(cfg)
    pc = gpd.read_file(p.parcel_changes_for(model))
    parcels = gpd.read_file(p.parcels_clipped)

    try:
        vp = value_per_sqft(parcels, cfg)
    except ValueError:
        log.info("too few recent builds in the box, using all of Wake County")
        vp = value_per_sqft(parcels, cfg, county=_county_value_table(cfg))
    metrics = _load_metrics(cfg)
    precision = metrics["precision"] if metrics else None
    if precision is None:
        log.warning("no metrics.json yet: headline money stays empty until validation is scored")
    money, totals = estimate_missed_tax(pc, precision, cfg, vp.value)
    money.to_file(p.parcel_changes, layer="parcels", driver="GPKG")
    shutil.copyfile(p.building_changes_for(model), p.building_changes)

    v = cfg.valuation
    valuation = {
        "model": model,
        "value_per_sqft": vp.to_dict(),
        "rates_cents_per_100": {
            "county": v.county_rate_cents_per_100,
            "municipal": v.municipal_rate_cents_per_100,
        },
        "assessment_ratio": v.assessment_ratio,
        "include_fire_tax": v.include_fire_tax,
        "tax_year": v.tax_year,
        "formula": (
            "yearly_tax = added_sqft * value_per_sqft * assessment_ratio * rate_cents / 100 / 100;"
            " reported = sum(flagged) * precision"
        ),
        "validation": metrics.get("labeled_by", "owner") if metrics else "pending",
        **totals,
    }
    p.valuation.write_text(json.dumps(valuation, indent=2), "utf-8")
    log.info(
        "value per sq ft $%.2f (%s, n=%d); raw yearly tax on flags $%.0f",
        vp.value,
        vp.scope,
        vp.n,
        totals["est_yearly_tax_usd_raw"],
    )

    allp = all_parcels_with_changes(parcels, pc, cfg)
    hexes = to_h3(allp, cfg.privacy.h3_resolution, cfg.privacy.min_parcels_per_hex)
    web = p.web_data
    web.mkdir(parents=True, exist_ok=True)
    export_pmtiles(hexes, web / "changes_h3.pmtiles")
    stats = build_stats(cfg, pc, totals, metrics, hexes, model)
    write_stats(stats, web / "stats.json")
    make_figures(cfg, hexes, stats)
    problems = audit_public_outputs(web, cfg.privacy.min_parcels_per_hex)
    if problems:
        raise RuntimeError("public output failed the privacy audit: " + "; ".join(problems))
    log.info(
        "public hexes: %d (min %d parcels each); privacy audit passed",
        len(hexes),
        cfg.privacy.min_parcels_per_hex,
    )
    write_review_table(cfg, money)
