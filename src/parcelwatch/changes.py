"""F5/F6/F7: object-based change classification, parcel roll-up and permit check (M4).

Never pixel differencing: NAIP is only accurate to about ±6 m, so building objects are
matched with a buffer tolerance instead (TRD section 3.1).
"""

from __future__ import annotations

import json
import logging
from datetime import date

import geopandas as gpd
import pandas as pd

from parcelwatch.config import Config
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

CHANGE_COLUMNS = [
    "bldg_id",
    "year",
    "change",
    "area_m2",
    "matched_before_m2",
    "added_m2",
    "model",
    "score",
    "geometry",
]
PARCEL_COLUMNS = [
    "parcel_id",
    "city",
    "n_new",
    "n_expanded",
    "n_demolished",
    "added_m2",
    "added_sqft",
    "geometry",
]


def require_crs(gdf: gpd.GeoDataFrame, crs: str, name: str) -> None:
    """Fail loudly unless ``gdf`` is in ``crs`` (runtime invariant, TRD section 11).

    Raises:
        ValueError: If the CRS is missing or different.
    """
    if gdf.crs is None or gdf.crs != crs:
        raise ValueError(f"{name} must be in {crs} before geometry math, got {gdf.crs}")


def _prep(gdf: gpd.GeoDataFrame, year: int, min_area: float, model: str) -> gpd.GeoDataFrame:
    """Standardize one year's buildings: ids from input order, area, size filter."""
    g = gdf.reset_index(drop=True)
    out = gpd.GeoDataFrame(
        {
            "bldg_id": [f"{year}_{i}" for i in g.index],
            "year": year,
            "score": g["score"].astype(float) if "score" in g else float("nan"),
            "model": g["model"].astype(str) if "model" in g else model,
        },
        geometry=g.geometry.values,
        crs=g.crs,
        index=g.index,
    )
    out = out[out.geometry.notna() & ~out.geometry.is_empty]
    out["area_m2"] = out.geometry.area
    return out[out["area_m2"] >= min_area]


def _matches(left: gpd.GeoDataFrame, right: gpd.GeoDataFrame, tol: float) -> pd.DataFrame:
    """Pairs (left index, right index) where ``left`` intersects ``right`` buffered by ``tol``."""
    if left.empty or right.empty:
        return pd.DataFrame({"left": pd.Series(dtype=int), "right": pd.Series(dtype=int)})
    buf = gpd.GeoDataFrame(geometry=right.geometry.buffer(tol), crs=right.crs)
    j = gpd.sjoin(left[["geometry"]], buf, predicate="intersects", how="inner")
    return pd.DataFrame({"left": j.index, "right": j["index_right"].to_numpy()})


def classify_changes(
    before: gpd.GeoDataFrame,
    after: gpd.GeoDataFrame,
    cfg: Config,
    tolerance_m: float,
    model: str = "v0",
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Label After buildings new/expanded/unchanged and find demolished Before buildings.

    Implements TRD section 3.1 exactly. All geometry must be in the working CRS.

    Args:
        before: Before building polygons (optional ``score`` column).
        after: After building polygons (optional ``score`` column).
        cfg: Loaded config (``change`` thresholds, image years).
        tolerance_m: Match buffer in meters, from ``results/alignment_report.json``.
        model: Model tag written to the ``model`` column.

    Returns:
        ``(after_labeled, demolished)``, both with :data:`CHANGE_COLUMNS`.
    """
    crs = cfg.aoi.working_crs
    require_crs(before, crs, "before buildings")
    require_crs(after, crs, "after buildings")
    c = cfg.change
    b = _prep(before, cfg.imagery.before.year, c.min_building_area_m2, model)
    a = _prep(after, cfg.imagery.after.year, c.min_building_area_m2, model)

    # Steps 2-4: each After building against Before buildings buffered by the tolerance.
    pairs = _matches(a, b, tolerance_m)
    matched = pairs.assign(b_area=b["area_m2"].reindex(pairs["right"]).to_numpy())
    matched_area = matched.groupby("left")["b_area"].sum()
    a["matched_before_m2"] = matched_area.reindex(a.index)
    gain = a["area_m2"] - a["matched_before_m2"]
    is_new = a["matched_before_m2"].isna()
    is_expanded = (
        ~is_new
        & (gain >= c.expanded_min_added_m2)
        & (a["area_m2"] >= c.expanded_min_ratio * a["matched_before_m2"])
    )
    a["change"] = "unchanged"
    a.loc[is_expanded, "change"] = "expanded"
    a.loc[is_new, "change"] = "new"
    a["added_m2"] = 0.0
    a.loc[is_new, "added_m2"] = a.loc[is_new, "area_m2"]
    a.loc[is_expanded, "added_m2"] = gain[is_expanded].clip(lower=0)

    # Step 5: Before buildings that touch no buffered After building.
    hit = set(_matches(b, a, tolerance_m)["left"])
    d = b[~b.index.isin(hit)].copy()
    d["change"] = "demolished"
    d["matched_before_m2"] = float("nan")
    d["added_m2"] = 0.0

    if (a["added_m2"] < 0).any():  # pragma: no cover - invariant
        raise AssertionError("added_m2 must be >= 0")
    after_labeled = gpd.GeoDataFrame(a[CHANGE_COLUMNS], crs=crs).reset_index(drop=True)
    demolished = gpd.GeoDataFrame(d[CHANGE_COLUMNS], crs=crs).reset_index(drop=True)
    log.info(
        "changes: %d after buildings (%d new, %d expanded), %d demolished, tolerance %.1f m",
        len(after_labeled),
        int(is_new.sum()),
        int(is_expanded.sum()),
        len(demolished),
        tolerance_m,
    )
    return after_labeled, demolished


def combine_changes(
    after_labeled: gpd.GeoDataFrame, demolished: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Stack labeled After buildings and demolished Before buildings into one layer."""
    frames = [f for f in (after_labeled, demolished) if not f.empty]
    if not frames:
        return after_labeled.iloc[0:0].copy()
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=after_labeled.crs)


def rollup_to_parcels(
    changes: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame, cfg: Config
) -> gpd.GeoDataFrame:
    """Assign each changed building to one parcel by representative point and aggregate.

    One building maps to exactly one parcel (its representative point falls ``within`` it);
    buildings outside every parcel are logged as orphans and skipped. ``added_m2`` sums
    only the change types in ``change.flag_change_types``, so it's the area a flag claims.

    Args:
        changes: Output of :func:`combine_changes`.
        parcels: Parcels in the working CRS with the config parcel id and city fields.
        cfg: Loaded config.

    Returns:
        One row per changed parcel with :data:`PARCEL_COLUMNS`.
    """
    crs = cfg.aoi.working_crs
    require_crs(changes, crs, "changes")
    require_crs(parcels, crs, "parcels")
    pid, city = cfg.fields.parcel_id, cfg.fields.city
    changed = changes[changes["change"] != "unchanged"]
    p = gpd.GeoDataFrame(
        {
            "parcel_id": parcels[pid].astype(str).to_numpy(),
            "city": parcels[city].fillna("").astype(str).to_numpy() if city in parcels else "",
        },
        geometry=parcels.geometry.to_numpy(),
        crs=crs,
    )
    empty = gpd.GeoDataFrame({c: [] for c in PARCEL_COLUMNS[:-1]}, geometry=[], crs=crs)
    if changed.empty:
        return empty
    pts = gpd.GeoDataFrame(changed[["change", "added_m2"]], geometry=changed.representative_point())
    j = gpd.sjoin(pts, p[["parcel_id", "geometry"]], predicate="within", how="left")
    j = j[~j.index.duplicated(keep="first")]  # overlapping parcels: still one parcel each
    orphans = j["parcel_id"].isna()
    if orphans.any():
        log.warning("%d changed buildings are orphaned (in no parcel)", int(orphans.sum()))
    j = j[~orphans]
    if j.empty:
        return empty
    counts = pd.crosstab(j["parcel_id"], j["change"])
    agg = pd.DataFrame(index=counts.index)
    for kind in ("new", "expanded", "demolished"):
        agg[f"n_{kind}"] = counts.get(kind, 0)
    flaggable = j["change"].isin(cfg.change.flag_change_types)
    agg["added_m2"] = j["added_m2"].where(flaggable, 0.0).groupby(j["parcel_id"]).sum()
    agg["added_sqft"] = agg["added_m2"] * cfg.valuation.sqft_per_m2
    out = p.drop_duplicates("parcel_id").merge(agg, left_on="parcel_id", right_index=True)
    return gpd.GeoDataFrame(out[PARCEL_COLUMNS], crs=crs).reset_index(drop=True)


def attach_permits(
    parcel_changes: gpd.GeoDataFrame,
    permits: gpd.GeoDataFrame,
    window: tuple[date, date],
    cfg: Config,
) -> gpd.GeoDataFrame:
    """Count permits per parcel (spatial within or PIN match) and set ``flag_unpermitted``.

    A parcel is flagged when it has no counting permit in the window and at least one
    change of a type in ``change.flag_change_types``.

    Args:
        parcel_changes: Output of :func:`rollup_to_parcels`.
        permits: Permit points in the working CRS with an ``issue_date`` column.
        window: Inclusive (start, end) permit window.
        cfg: Loaded config (counting types, field names).

    Returns:
        ``parcel_changes`` with ``n_permits`` and ``flag_unpermitted``.
    """
    crs = cfg.aoi.working_crs
    require_crs(parcel_changes, crs, "parcel_changes")
    f = cfg.fields
    out = parcel_changes.copy()
    flaggable = pd.concat(
        [out[f"n_{kind}"] > 0 for kind in cfg.change.flag_change_types], axis=1
    ).any(axis=1)
    if permits.empty or out.empty:
        out["n_permits"] = 0
        out["flag_unpermitted"] = flaggable
        return out
    require_crs(permits, crs, "permits")
    start, end = window
    ok = (
        permits["issue_date"].notna()
        & (permits["issue_date"] >= start)
        & (permits["issue_date"] <= end)
        & permits[f.permit_type].isin(cfg.permits.counting_types)
    )
    pm = permits[ok].reset_index(drop=True)
    pm["_pid"] = pm.index
    pairs: list[pd.DataFrame] = []
    if "spatial" in cfg.permits.match_by:
        pts = pm[pm.geometry.notna() & ~pm.geometry.is_empty]
        if not pts.empty:
            j = gpd.sjoin(
                pts[["_pid", "geometry"]],
                out[["parcel_id", "geometry"]],
                predicate="within",
            )
            pairs.append(j[["parcel_id", "_pid"]])
    if "pin" in cfg.permits.match_by:
        pin = pm[[f.permit_parcel_id, "_pid"]].rename(columns={f.permit_parcel_id: "parcel_id"})
        pin["parcel_id"] = pin["parcel_id"].astype(str).str.strip()
        pairs.append(pin.merge(out[["parcel_id"]], on="parcel_id"))
    matched = pd.concat(pairs, ignore_index=True).drop_duplicates() if pairs else pd.DataFrame()
    n = matched.groupby("parcel_id")["_pid"].nunique() if not matched.empty else pd.Series()
    out["n_permits"] = out["parcel_id"].map(n).fillna(0).astype(int)
    out["flag_unpermitted"] = (out["n_permits"] == 0) & flaggable
    return out


def load_tolerance(cfg: Config) -> float:
    """Read the match tolerance from ``results/alignment_report.json``, else the config default."""
    report = Paths(cfg.root).alignment_report
    if report.exists():
        tol = float(json.loads(report.read_text("utf-8"))["match_tolerance_m"])
        log.info("match tolerance %.2f m from %s", tol, report.name)
        return tol
    log.warning(
        "no alignment report, using default tolerance %.1f m",
        cfg.change.match_tolerance_m,
    )
    return cfg.change.match_tolerance_m


def run(cfg: Config, model: str, *, force: bool = False) -> None:
    """Run classification, roll-up and permit check for the chosen model."""
    p = Paths(cfg.root)
    out_b, out_p = p.building_changes_for(model), p.parcel_changes_for(model)
    if out_b.exists() and out_p.exists() and not force:
        log.info("changes for %s already exist, skipping (use --force)", model)
        return
    before = gpd.read_file(p.buildings("before", model))
    after = gpd.read_file(p.buildings("after", model))
    parcels = gpd.read_file(p.parcels_clipped)
    permits = gpd.read_file(p.permits_clipped)
    permits["issue_date"] = pd.to_datetime(permits["issue_date"]).dt.date
    tol = load_tolerance(cfg)
    a, d = classify_changes(before, after, cfg, tol, model=model)
    changes = combine_changes(a, d)
    pc = rollup_to_parcels(changes, parcels[parcels["in_box"]], cfg)
    window = (cfg.permits.window_start, cfg.permits.window_end)
    pc = attach_permits(pc, permits, window, cfg)
    for path in (out_b, out_p):
        path.parent.mkdir(parents=True, exist_ok=True)
    changes.to_file(out_b, layer="buildings", driver="GPKG")
    pc.to_file(out_p, layer="parcels", driver="GPKG")
    log.info(
        "parcels changed: %d, flagged unpermitted: %d, added %.0f sq ft on flagged",
        len(pc),
        int(pc["flag_unpermitted"].sum()),
        float(pc.loc[pc["flag_unpermitted"], "added_sqft"].sum()),
    )
