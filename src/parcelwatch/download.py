"""F1: download NAIP, Wake parcels/permits/town limits and Overture buildings (milestone M1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import geopandas as gpd

from parcelwatch.config import BBox, Config


def download_naip_items(item_ids: list[str], out_dir: Path, cfg: Config) -> list[Path]:
    """Download NAIP GeoTIFFs by exact STAC item ID from Planetary Computer.

    Args:
        item_ids: STAC item IDs from ``imagery.before.items`` or ``imagery.after.items``.
        out_dir: Destination folder under ``data/raw/``.
        cfg: Loaded config (STAC URL and collection).

    Returns:
        Paths of the downloaded tiles.
    """
    raise NotImplementedError("M1")


def download_hub_file(url: str, out: Path, *, force: bool = False) -> Path:
    """Download one full-county ArcGIS Hub file, skipping if it already exists.

    Args:
        url: ArcGIS Hub download URL from ``vectors.*_download``.
        out: Destination file under ``data/raw/``.
        force: Re-download even if ``out`` exists.

    Returns:
        ``out``.
    """
    raise NotImplementedError("M1")


def load_parcels(zip_path: Path, bbox: BBox, cfg: Config) -> gpd.GeoDataFrame:
    """Read the county parcel zip, drop owner/address columns, clip, reproject, make valid.

    Args:
        zip_path: Full-county parcel shapefile zip (EPSG:2264).
        bbox: Study box in the working CRS.
        cfg: Loaded config (field names, never_load list, CRSs).

    Returns:
        Parcels in the working CRS with no ``never_load`` columns.
    """
    raise NotImplementedError("M1")


def load_permits(
    csv_path: Path, bbox: BBox, window: tuple[date, date], cfg: Config
) -> gpd.GeoDataFrame:
    """Read the permit CSV, keep counting types inside the window, build points, clip.

    Args:
        csv_path: Full-county permit CSV.
        bbox: Study box in the working CRS.
        window: Inclusive (start, end) issue-date window.
        cfg: Loaded config (field names, counting types, CRSs).

    Returns:
        Permit points in the working CRS.
    """
    raise NotImplementedError("M1")


def download_overture(bbox_wgs84: BBox, out: Path, *, force: bool = False) -> Path:
    """Fetch Overture building footprints for the box and cache them as GeoParquet.

    Args:
        bbox_wgs84: Study box in lon/lat.
        out: Destination parquet under ``data/raw/``.
        force: Re-download even if ``out`` exists.

    Returns:
        ``out``.
    """
    raise NotImplementedError("M1")


def run(cfg: Config, *, force: bool = False) -> None:
    """Run every F1 download for the config."""
    raise NotImplementedError("M1")
