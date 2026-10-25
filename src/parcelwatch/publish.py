"""Public outputs: H3 aggregation, PMTiles and stats.json (milestone M7).

Only ``changes_h3`` and ``stats.json`` are ever public. No parcel IDs, addresses or owners.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import geopandas as gpd

# Keys that must never appear in a public file (TRD section 8). Matched case-insensitively.
FORBIDDEN_PUBLIC_KEYS: frozenset[str] = frozenset(
    {"parcel_id", "pin_num", "pin", "reid", "real_estate_id", "owner", "address", "site_address"}
)
FORBIDDEN_KEY_PREFIXES: tuple[str, ...] = ("owner", "addr")
# Wake County PINs are 10 digits; no public string value may look like one.
PIN_PATTERN = re.compile(r"(?<!\d)\d{10}(?!\d)")
PUBLIC_H3_COLUMNS: tuple[str, ...] = ("h3", "n_parcels", "n_changed", "n_flagged", "added_sqft")
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

    Args:
        parcel_changes: All parcels in the box with change and flag columns.
        res: H3 resolution (9).
        min_parcels: Minimum parcels per published hex (5).

    Returns:
        Hex polygons in EPSG:4326 with only :data:`PUBLIC_H3_COLUMNS`.
    """
    raise NotImplementedError("M7")


def export_pmtiles(gdf: gpd.GeoDataFrame, out: Path) -> Path:
    """Write hexes to PMTiles via tippecanoe.

    Args:
        gdf: Output of :func:`to_h3`.
        out: ``web/data/changes_h3.pmtiles``.

    Returns:
        ``out``.
    """
    raise NotImplementedError("M7")


def write_stats(stats: dict[str, Any], out: Path) -> Path:
    """Write the public headline numbers to ``web/data/stats.json``.

    Args:
        stats: Keys per TRD section 4 ``stats.json``.
        out: Output path.

    Returns:
        ``out``.
    """
    raise NotImplementedError("M7")
