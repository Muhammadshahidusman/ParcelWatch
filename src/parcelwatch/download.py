"""F1: download NAIP, Wake parcels/permits/town limits and Overture buildings (milestone M1)."""

from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely.geometry import box

from parcelwatch.config import BBox, Config
from parcelwatch.http import get_with_retry
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

CHUNK = 1 << 20


def _stream_to(url: str, out: Path) -> Path:
    """Stream a URL to ``out`` through a ``.part`` file so partial downloads never count."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    with get_with_retry(url, stream=True) as resp, part.open("wb") as fh:
        for chunk in resp.iter_content(CHUNK):
            fh.write(chunk)
    part.replace(out)
    log.info("downloaded %s (%.1f MB)", out.name, out.stat().st_size / 1e6)
    return out


def transform_bbox(bbox: BBox, src_crs: str, dst_crs: str) -> BBox:
    """Transform a bbox and return the bounds enclosing it in ``dst_crs``.

    Args:
        bbox: ``(min_x, min_y, max_x, max_y)`` in ``src_crs``.
        src_crs: Source CRS string.
        dst_crs: Target CRS string.

    Returns:
        The enclosing bbox in ``dst_crs`` (densified edges, so it is never too small).
    """
    t = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    x0, y0, x1, y1 = t.transform_bounds(*bbox, densify_pts=21)
    return (x0, y0, x1, y1)


NAIP_MARGIN_M = 100.0  # read this much beyond the box so alignment never runs out of pixels
GDAL_HTTP_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
}


def _read_cog_window(href: str, bbox: BBox, bbox_crs: str, out: Path) -> Path:
    """Copy the part of a remote Cloud-Optimized GeoTIFF that covers ``bbox`` to ``out``.

    Pixels are copied unchanged (same grid, dtype and bands), so the result is still raw.
    """
    import rasterio
    from rasterio.windows import Window, from_bounds

    with rasterio.Env(**GDAL_HTTP_ENV), rasterio.open(href) as src:
        tb = transform_bbox(bbox, bbox_crs, src.crs.to_string())
        win = from_bounds(*tb, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            width=int(win.width),
            height=int(win.height),
            transform=src.window_transform(win),
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="deflate",
            predictor=2,
            interleave="pixel",
        )
        part = out.with_name(out.name + ".part")
        out.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(part, "w", **profile) as dst:
            step = 1024
            for row in range(0, int(win.height), step):
                h = min(step, int(win.height) - row)
                sub = Window(win.col_off, win.row_off + row, win.width, h)
                dst.write(src.read(window=sub), window=Window(0, row, win.width, h))
            dst.update_tags(source_href=href.split("?")[0])
    part.replace(out)
    log.info(
        "NAIP window %s: %dx%d px (%.1f MB)",
        out.name,
        win.width,
        win.height,
        out.stat().st_size / 1e6,
    )
    return out


def download_naip_items(item_ids: list[str], out_dir: Path, cfg: Config) -> list[Path]:
    """Download the box-covering part of NAIP tiles by exact STAC item ID.

    Tiles are Cloud-Optimized GeoTIFFs, so only the window covering the study box (plus a
    100 m margin) is read through HTTP range requests. Each asset URL is signed right before
    it is read, since signatures expire. Tiles run in parallel.

    Args:
        item_ids: STAC item IDs from ``imagery.before.items`` or ``imagery.after.items``.
        out_dir: Destination folder under ``data/raw/``.
        cfg: Loaded config (STAC URL, collection, box).

    Returns:
        Paths of the downloaded tiles, in ``item_ids`` order.
    """
    from concurrent.futures import ThreadPoolExecutor

    import planetary_computer
    import pystac_client

    catalog = pystac_client.Client.open(cfg.imagery.stac_url)
    collection = catalog.get_collection(cfg.imagery.collection)
    if collection is None:
        raise FileNotFoundError(f"collection {cfg.imagery.collection} not found")
    x0, y0, x1, y1 = cfg.aoi.bbox_utm17n
    m = NAIP_MARGIN_M
    bbox = (x0 - m, y0 - m, x1 + m, y1 + m)

    def fetch(item_id: str) -> Path:
        out = out_dir / f"{item_id}.tif"
        if out.exists():
            log.info("NAIP %s already downloaded", item_id)
            return out
        item = collection.get_item(item_id)
        if item is None:
            raise FileNotFoundError(f"NAIP item {item_id} not in {cfg.imagery.collection}")
        href = planetary_computer.sign(item.assets["image"].href)
        return _read_cog_window(href, bbox, cfg.aoi.working_crs, out)

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(fetch, item_ids))


def download_hub_file(url: str, out: Path, *, force: bool = False) -> Path:
    """Download one full-county ArcGIS Hub file, skipping if it already exists.

    Args:
        url: ArcGIS Hub download URL from ``vectors.*_download``.
        out: Destination file under ``data/raw/``.
        force: Re-download even if ``out`` exists.

    Returns:
        ``out``.
    """
    if out.exists() and not force:
        log.info("%s already downloaded", out.name)
        return out
    return _stream_to(url, out)


def _vsizip(zip_path: Path) -> str:
    """Return a GDAL path to the first shapefile inside a zip."""
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        shps = [n for n in zf.namelist() if n.lower().endswith(".shp")]
    if not shps:
        raise FileNotFoundError(f"no .shp inside {zip_path}")
    return f"/vsizip/{zip_path.resolve().as_posix()}/{shps[0]}"


SHAPEFILE_FIELD_LEN = 10


def _parcel_fields(cfg: Config) -> list[str]:
    """Config field names that live on the parcel layer."""
    f = cfg.fields
    return [
        f.parcel_id,
        f.real_estate_id,
        f.building_value,
        f.land_value,
        f.total_value,
        f.heated_area_sqft,
        f.year_built,
        f.city,
        f.planning_jurisdiction,
        f.land_class,
    ]


def restore_shapefile_names(columns: list[str], wanted: list[str]) -> dict[str, str]:
    """Map shapefile-truncated column names (10 chars) back to the full config names.

    Args:
        columns: Column names as read.
        wanted: Full field names from the config.

    Returns:
        A rename map ``{truncated: full}`` for names that were cut and are unambiguous.
    """
    present = set(columns)
    renames: dict[str, str] = {}
    for full in wanted:
        short = full[:SHAPEFILE_FIELD_LEN]
        unique = sum(w[:SHAPEFILE_FIELD_LEN] == short for w in wanted) == 1
        if full not in present and short in present and short != full and unique:
            renames[short] = full
    return renames


def load_parcels(zip_path: Path, bbox: BBox, cfg: Config) -> gpd.GeoDataFrame:
    """Read the county parcels for the box without ever loading owner or address columns.

    The schema is read first and the ``never_load`` fields are excluded from the read
    itself. Parcels that intersect the box are kept whole, reprojected to the working CRS
    and made valid. ``in_box`` marks parcels whose representative point is inside the box.

    Args:
        zip_path: Full-county parcel shapefile zip (or any OGR-readable path).
        bbox: Study box in the working CRS.
        cfg: Loaded config (field names, never_load list, CRSs).

    Returns:
        Parcels in the working CRS with no ``never_load`` columns.
    """
    src = _vsizip(zip_path) if zip_path.suffix.lower() == ".zip" else str(zip_path)
    info = pyogrio.read_info(src)
    banned = {f.upper() for f in cfg.fields.never_load}
    columns = [f for f in info["fields"] if f.upper() not in banned]
    src_crs = info["crs"] or cfg.vectors.parcels_source_crs
    src_bbox = transform_bbox(bbox, cfg.aoi.working_crs, src_crs)
    gdf = gpd.read_file(src, columns=columns, bbox=src_bbox, engine="pyogrio")
    if gdf.crs is None:
        gdf = gdf.set_crs(cfg.vectors.parcels_source_crs)
    assert not banned & {c.upper() for c in gdf.columns}, "owner/address column leaked"
    gdf = gdf.rename(columns=restore_shapefile_names(list(gdf.columns), _parcel_fields(cfg)))
    gdf = gdf.to_crs(cfg.aoi.working_crs)
    gdf["geometry"] = gdf.geometry.make_valid()
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    aoi = box(*bbox)
    gdf = gdf[gdf.intersects(aoi)].copy()
    gdf["in_box"] = gdf.representative_point().within(aoi)
    pid = cfg.fields.parcel_id
    gdf[pid] = gdf[pid].astype(str).str.strip()
    log.info(
        "parcels: %d intersect the box (%d centered in it)",
        len(gdf),
        gdf["in_box"].sum(),
    )
    return gdf.reset_index(drop=True)


def parse_issue_dates(values: pd.Series) -> pd.Series:
    """Parse Wake ``ISSUE_DATE`` text (``YYYY/MM/DD 00:00:00+00``) to dates; bad → NaT."""
    parsed = pd.to_datetime(values, format="%Y/%m/%d %H:%M:%S%z", errors="coerce", utc=True)
    return parsed.dt.date


def load_permits(
    csv_path: Path,
    bbox: BBox,
    window: tuple[date, date],
    cfg: Config,
    pins: set[str] | None = None,
) -> gpd.GeoDataFrame:
    """Read the permit CSV, keep counting types inside the window, build points, clip.

    A permit is kept if its point is inside the box, or (when ``pins`` is given) its PIN
    matches a parcel in the box, so PIN matching still works for permits with bad or
    missing coordinates.

    Args:
        csv_path: Full-county permit CSV.
        bbox: Study box in the working CRS.
        window: Inclusive (start, end) issue-date window.
        cfg: Loaded config (field names, counting types, CRSs).
        pins: Optional PIN_NUM values of box parcels.

    Returns:
        Permit points in the working CRS (geometry is None where coordinates are missing).
    """
    f = cfg.fields
    df = pd.read_csv(csv_path, dtype={f.permit_parcel_id: str, f.permit_id: str}, low_memory=False)
    df["issue_date"] = parse_issue_dates(df[f.permit_issue_date])
    start, end = window
    in_window = df["issue_date"].notna() & (df["issue_date"] >= start) & (df["issue_date"] <= end)
    counting = df[f.permit_type].isin(cfg.permits.counting_types)
    df = df[in_window & counting].copy()
    df[f.permit_parcel_id] = df[f.permit_parcel_id].fillna("").astype(str).str.strip()
    x = pd.to_numeric(df[f.permit_x], errors="coerce")
    y = pd.to_numeric(df[f.permit_y], errors="coerce")
    pts = gpd.GeoSeries.from_xy(x, y, crs=cfg.vectors.permits_xy_crs)
    pts[x.isna() | y.isna()] = None
    gdf = gpd.GeoDataFrame(
        df, geometry=pts.to_crs(cfg.aoi.working_crs).values, crs=cfg.aoi.working_crs
    )
    inside = gdf.geometry.within(box(*bbox)).fillna(False)
    keep = inside | gdf[f.permit_parcel_id].isin(pins) if pins else inside
    gdf = gdf[keep].copy()
    gdf["in_box"] = inside[keep]
    log.info(
        "permits: %d counting-type permits in window, %d with a point in the box",
        len(gdf),
        int(gdf["in_box"].sum()),
    )
    return gdf.reset_index(drop=True)


def download_overture(
    bbox_wgs84: BBox, out: Path, *, overture_type: str, force: bool = False
) -> Path:
    """Fetch Overture building footprints for the box and cache them as GeoParquet.

    Args:
        bbox_wgs84: Study box in lon/lat.
        out: Destination parquet under ``data/raw/``.
        overture_type: Overture feature type (``building``).
        force: Re-download even if ``out`` exists.

    Returns:
        ``out``.
    """
    if out.exists() and not force:
        log.info("%s already downloaded", out.name)
        return out
    from overturemaps import core

    gdf = core.geodataframe(overture_type, bbox=bbox_wgs84)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    keep = [c for c in ("id", "height", "num_floors", "class", "subtype", "geometry") if c in gdf]
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf[keep].to_parquet(out)
    log.info("overture: %d %s features", len(gdf), overture_type)
    return out


def run(cfg: Config, *, force: bool = False) -> None:
    """Run every F1 download for the config into ``data/raw/``."""
    p = Paths(cfg.root)
    for key, acq in (("before", cfg.imagery.before), ("after", cfg.imagery.after)):
        out_dir = p.naip_raw(key)
        if force and out_dir.exists():
            shutil.rmtree(out_dir)
        download_naip_items(acq.items, out_dir, cfg)
    v = cfg.vectors
    download_hub_file(v.parcels_download, p.parcels_zip, force=force)
    download_hub_file(v.permits_download, p.permits_csv, force=force)
    download_hub_file(v.corporate_limits_download, p.corporate_limits, force=force)
    download_overture(
        cfg.aoi.bbox_wgs84,
        p.overture_buildings,
        overture_type=v.overture_type,
        force=force,
    )
