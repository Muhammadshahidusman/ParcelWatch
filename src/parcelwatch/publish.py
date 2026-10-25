"""Public outputs: H3 aggregation, PMTiles and stats.json (milestone M7).

Only ``changes_h3`` and ``stats.json`` are ever public. No parcel IDs, addresses or owners.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

log = logging.getLogger(__name__)

# Keys that must never appear in a public file (TRD section 8). Matched case-insensitively.
FORBIDDEN_PUBLIC_KEYS: frozenset[str] = frozenset(
    {
        "parcel_id",
        "pin_num",
        "pin",
        "reid",
        "real_estate_id",
        "owner",
        "address",
        "site_address",
    }
)
FORBIDDEN_KEY_PREFIXES: tuple[str, ...] = ("owner", "addr")
# Wake County PINs are 10 digits; no public string value may look like one.
PIN_PATTERN = re.compile(r"(?<!\d)\d{10}(?!\d)")
PUBLIC_H3_COLUMNS: tuple[str, ...] = (
    "h3",
    "n_parcels",
    "n_changed",
    "n_flagged",
    "added_sqft",
)
# Files allowed in web/data. PMTiles must sit next to the GeoJSON they were built from,
# so the audit can check the exact features that went into the tiles.
ALLOWED_PUBLIC_SUFFIXES: tuple[str, ...] = (".json", ".geojson", ".pmtiles")


def _walk(obj: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield ``(json_path, key, value)`` for every key in a nested JSON object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", str(k), v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _audit_json(path: Path, min_parcels: int) -> list[str]:
    """Return privacy problems found in one public JSON or GeoJSON file."""
    problems: list[str] = []
    data = json.loads(path.read_text("utf-8"))
    for where, key, value in _walk(data):
        k = key.lower()
        if k in FORBIDDEN_PUBLIC_KEYS or k.startswith(FORBIDDEN_KEY_PREFIXES):
            problems.append(f"{path.name}{where}: forbidden key {key!r}")
        if k != "h3" and isinstance(value, str) and PIN_PATTERN.search(value):
            problems.append(f"{path.name}{where}: value looks like a parcel PIN")
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties") or {}
            n = props.get("n_parcels")
            if n is None or n < min_parcels:
                problems.append(f"{path.name} feature {i}: n_parcels={n} < {min_parcels}")
    return problems


def audit_public_outputs(public_dir: Path, min_parcels: int) -> list[str]:
    """Check every file in the public web data folder against the privacy rules.

    Rules: only JSON, GeoJSON and PMTiles files; no parcel ID, PIN, owner or address keys;
    no PIN-like string values; every hex has at least ``min_parcels`` parcels; every
    PMTiles file has its source GeoJSON next to it (that GeoJSON is what gets audited).

    Args:
        public_dir: ``web/data``. A missing folder has nothing public, so it passes.
        min_parcels: ``privacy.min_parcels_per_hex``.

    Returns:
        A list of problems; empty means the folder is safe to publish.
    """
    if not public_dir.exists():
        return []
    problems: list[str] = []
    for f in sorted(p for p in public_dir.rglob("*") if p.is_file()):
        suffix = f.suffix.lower()
        if suffix not in ALLOWED_PUBLIC_SUFFIXES:
            problems.append(f"{f.name}: file type {suffix!r} is not allowed in public data")
        elif suffix == ".pmtiles":
            if not f.with_suffix(".geojson").exists():
                problems.append(f"{f.name}: no source {f.stem}.geojson to audit")
        else:
            try:
                problems.extend(_audit_json(f, min_parcels))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                problems.append(f"{f.name}: unreadable ({exc})")
    return problems


def to_h3(parcel_changes: gpd.GeoDataFrame, res: int, min_parcels: int) -> gpd.GeoDataFrame:
    """Aggregate parcels to H3 cells and drop cells with fewer than ``min_parcels`` parcels.

    Each parcel goes to the cell holding its representative point. ``added_sqft`` is the
    added area on flagged parcels, rounded to the nearest 100.

    Args:
        parcel_changes: All parcels in the box with ``changed``, ``flag_unpermitted`` and
            ``added_sqft`` columns.
        res: H3 resolution (9).
        min_parcels: Minimum parcels per published hex (5).

    Returns:
        Hex polygons in EPSG:4326 with only :data:`PUBLIC_H3_COLUMNS`.
    """
    import h3
    from shapely.geometry import Polygon

    pts = parcel_changes.representative_point().to_crs("EPSG:4326")
    df = pd.DataFrame(
        {
            "h3": [h3.latlng_to_cell(p.y, p.x, res) for p in pts],
            "changed": parcel_changes["changed"].astype(bool).to_numpy(),
            "flagged": parcel_changes["flag_unpermitted"].fillna(False).astype(bool).to_numpy(),
            "added": parcel_changes["added_sqft"].fillna(0).to_numpy(),
        }
    )
    df["added_flagged"] = df["added"].where(df["flagged"], 0.0)
    agg = df.groupby("h3").agg(
        n_parcels=("h3", "size"),
        n_changed=("changed", "sum"),
        n_flagged=("flagged", "sum"),
        added_sqft=("added_flagged", "sum"),
    )
    agg = agg[agg["n_parcels"] >= min_parcels].reset_index()
    agg["added_sqft"] = (agg["added_sqft"] / 100).round() * 100
    for col in ("n_parcels", "n_changed", "n_flagged"):
        agg[col] = agg[col].astype(int)
    geoms = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in agg["h3"]]
    return gpd.GeoDataFrame(agg[list(PUBLIC_H3_COLUMNS)], geometry=geoms, crs="EPSG:4326")


def export_pmtiles(gdf: gpd.GeoDataFrame, out: Path, layer: str = "changes_h3") -> Path:
    """Write hexes to GeoJSON and, when tippecanoe is installed, to PMTiles.

    The GeoJSON is always written next to ``out`` (it is the audited source of the tiles
    and the fallback the web map loads when no PMTiles file exists).

    Args:
        gdf: Output of :func:`to_h3`.
        out: ``web/data/changes_h3.pmtiles``.
        layer: Vector tile layer name.

    Returns:
        ``out`` if PMTiles were written, else the GeoJSON path.
    """
    import shutil
    import subprocess

    out.parent.mkdir(parents=True, exist_ok=True)
    geojson = out.with_suffix(".geojson")
    gdf.to_file(geojson, driver="GeoJSON", COORDINATE_PRECISION=6)
    exe = shutil.which("tippecanoe")
    if exe is None:
        log.warning("tippecanoe not found; the web map will load %s instead", geojson.name)
        if out.exists():
            out.unlink()
        return geojson
    subprocess.run(
        [
            exe,
            "-o",
            str(out),
            "-l",
            layer,
            "-zg",
            "--force",
            "--no-tile-size-limit",
            str(geojson),
        ],
        check=True,
    )
    return out


def write_stats(stats: dict[str, Any], out: Path) -> Path:
    """Write the public headline numbers to ``web/data/stats.json``.

    Args:
        stats: Keys per TRD section 4 ``stats.json`` (plus hex color breaks).
        out: Output path.

    Returns:
        ``out``.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=2, default=str), "utf-8")
    return out


def quantile_breaks(values: pd.Series, k: int = 5) -> list[float]:
    """Return up to ``k - 1`` unique quantile break values for the hex color ramp."""
    v = values[values > 0]
    if v.empty:
        return []
    qs = sorted({float(v.quantile(i / k)) for i in range(1, k)})
    return qs
