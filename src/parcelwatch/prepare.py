"""F2: mosaic, align, clip and measure the Before/After offset (milestone M2)."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, box

from parcelwatch.config import BBox, Config
from parcelwatch.download import load_parcels, load_permits
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

GTIFF_PROFILE = {
    "driver": "GTiff",
    "tiled": True,
    "blockxsize": 512,
    "blockysize": 512,
    "compress": "deflate",
    "predictor": 2,
    "interleave": "pixel",
    "BIGTIFF": "IF_SAFER",
}
CHIP_HALF_M = 40.0  # chips are 80 x 80 m around each intersection
EDGE_MARGIN_M = 150.0  # keep check points this far inside the box
# Wake County inspects these towns' permits; any other town in the box breaks the permit check.
COUNTY_INSPECTED_TOWNS = {"WENDELL", "KNIGHTDALE", "ROLESVILLE", "ZEBULON"}
STABLE_ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified"}
MIN_MATCH_CORRELATION = 0.5  # a check point is usable only if both years show the same scene


def snap_bounds(bounds: BBox, transform: Any) -> BBox:
    """Expand ``bounds`` outward to whole pixels of ``transform``'s grid."""
    res_x, res_y = transform.a, -transform.e
    ox, oy = transform.c, transform.f
    x0 = ox + math.floor((bounds[0] - ox) / res_x) * res_x
    x1 = ox + math.ceil((bounds[2] - ox) / res_x) * res_x
    y1 = oy - math.floor((oy - bounds[3]) / res_y) * res_y
    y0 = oy - math.ceil((oy - bounds[1]) / res_y) * res_y
    return (x0, y0, x1, y1)


def mosaic(folder: Path, out: Path, cfg: Config) -> Path:
    """Mosaic one year's NAIP tiles onto a grid covering the box in the working CRS.

    The output grid is the first tile's native pixel grid snapped around the box, so the
    Before image is never resampled.

    Args:
        folder: Folder of raw tiles for one year.
        out: Output GeoTIFF under ``data/processed/``.
        cfg: Loaded config (box, CRS, GSD).

    Returns:
        ``out``.
    """
    import rasterio
    from rasterio.merge import merge

    tiles = sorted(folder.glob("*.tif"))
    if not tiles:
        raise FileNotFoundError(f"no NAIP tiles in {folder}")
    srcs = [rasterio.open(t) for t in tiles]
    try:
        for s in srcs:
            if s.crs != cfg.aoi.working_crs:
                raise ValueError(f"{s.name} is {s.crs}, expected {cfg.aoi.working_crs}")
            if abs(s.res[0] - cfg.imagery.gsd_m) > 1e-6:
                raise ValueError(f"{s.name} has {s.res[0]} m pixels, expected {cfg.imagery.gsd_m}")
        bounds = snap_bounds(cfg.aoi.bbox_utm17n, srcs[0].transform)
        data, transform = merge(srcs, bounds=bounds, res=cfg.imagery.gsd_m)
        profile = srcs[0].profile.copy()
    finally:
        for s in srcs:
            s.close()
    profile.update(
        GTIFF_PROFILE,
        height=data.shape[1],
        width=data.shape[2],
        transform=transform,
        count=data.shape[0],
        crs=cfg.aoi.working_crs,
    )
    profile.pop("nodata", None)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data)
        dst.descriptions = tuple(cfg.imagery.bands[: data.shape[0]])
    log.info(
        "mosaic %s: %d bands, %dx%d px",
        out.name,
        data.shape[0],
        data.shape[2],
        data.shape[1],
    )
    return out


def align_to(reference: Path, target: Path, out: Path) -> Path:
    """Resample ``target`` onto the exact grid (CRS, transform, shape) of ``reference``.

    Args:
        reference: Before mosaic.
        target: After mosaic (or a folder of After tiles' mosaic).
        out: Aligned After GeoTIFF.

    Returns:
        ``out``.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    with rasterio.open(reference) as ref, rasterio.open(target) as src:
        vrt_opts = {
            "crs": ref.crs,
            "transform": ref.transform,
            "width": ref.width,
            "height": ref.height,
            "resampling": Resampling.bilinear,
        }
        with WarpedVRT(src, **vrt_opts) as vrt:
            profile = ref.profile.copy()
            profile.update(GTIFF_PROFILE, count=src.count, dtype=src.dtypes[0])
            with rasterio.open(out, "w", **profile) as dst:
                for _, win in dst.block_windows(1):
                    dst.write(vrt.read(window=win), window=win)
                dst.descriptions = src.descriptions
    log.info("aligned %s onto %s grid", target.name, reference.name)
    return out


def _town_column(gdf: gpd.GeoDataFrame) -> str | None:
    """Find the column holding town names in the corporate limits layer."""
    for col in gdf.columns:
        if col == "geometry" or not (
            pd.api.types.is_string_dtype(gdf[col]) or pd.api.types.is_object_dtype(gdf[col])
        ):
            continue
        vals = gdf[col].dropna().astype(str).str.upper()
        if vals.str.contains("WENDELL").any() or vals.str.contains("RALEIGH").any():
            return str(col)
    return None


def jurisdiction_shares(limits: gpd.GeoDataFrame, aoi: BBox) -> dict[str, float]:
    """Percent of the box inside each town (the rest is unincorporated).

    Args:
        limits: Town limit polygons in the working CRS.
        aoi: Study box in the working CRS.

    Returns:
        ``{town: pct}`` plus ``unincorporated``.
    """
    box_geom = box(*aoi)
    col = _town_column(limits)
    if col is None:
        raise ValueError(f"no town name column in corporate limits: {list(limits.columns)}")
    clipped = limits.clip(box_geom)
    clipped = clipped.assign(town=clipped[col].astype(str).str.upper().str.strip())
    by_town = clipped.dissolve("town").area / box_geom.area * 100
    shares = {str(k): round(float(v), 1) for k, v in by_town.items() if v > 0.05}
    shares["unincorporated"] = round(100 - sum(shares.values()), 1)
    return shares


def clip_vectors(cfg: Config) -> dict[str, Path]:
    """Load and clip every raw vector layer to the box in the working CRS.

    Args:
        cfg: Loaded config.

    Returns:
        Map of layer name to clipped file path.
    """
    p = Paths(cfg.root)
    aoi = cfg.aoi.bbox_utm17n
    crs = cfg.aoi.working_crs
    p.processed.mkdir(parents=True, exist_ok=True)

    parcels = load_parcels(p.parcels_zip, aoi, cfg)
    parcels.to_file(p.parcels_clipped, layer="parcels", driver="GPKG")

    pins = set(parcels.loc[parcels["in_box"], cfg.fields.parcel_id])
    window = (cfg.permits.window_start, cfg.permits.window_end)
    permits = load_permits(p.permits_csv, aoi, window, cfg, pins=pins)
    # GeoPackage field names are case-insensitive: keep the parsed date, drop the raw text.
    out = permits.drop(columns=[cfg.fields.permit_issue_date, "SHAPE"], errors="ignore")
    out.assign(issue_date=out["issue_date"].astype(str)).to_file(
        p.permits_clipped, layer="permits", driver="GPKG"
    )

    ov = gpd.read_parquet(p.overture_buildings).to_crs(crs)
    ov = ov[ov.geometry.intersects(box(*aoi))]
    ov = ov[ov.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(drop=True)
    ov.to_file(p.overture_clipped, layer="buildings", driver="GPKG")
    log.info("overture buildings in box: %d", len(ov))

    limits = gpd.read_file(p.corporate_limits).to_crs(crs)
    if "EFFECTIVE" in limits:
        limits = limits[limits["EFFECTIVE"].astype(str).str.upper() != "NO"]
    limits["geometry"] = limits.geometry.make_valid()
    limits.clip(box(*aoi)).to_file(p.corporate_limits_clipped, layer="limits", driver="GPKG")
    shares = jurisdiction_shares(limits, aoi)
    other = sorted(set(shares) - COUNTY_INSPECTED_TOWNS - {"unincorporated"})
    if other:
        log.warning("box includes towns that may run their own inspections: %s", other)
    p.jurisdiction_check.parent.mkdir(parents=True, exist_ok=True)
    p.jurisdiction_check.write_text(
        json.dumps({"share_pct": shares, "non_county_inspected": other}, indent=2),
        "utf-8",
    )
    log.info("jurisdiction shares in box: %s", shares)
    return {
        "parcels": p.parcels_clipped,
        "permits": p.permits_clipped,
        "overture": p.overture_clipped,
        "corporate_limits": p.corporate_limits_clipped,
    }


# ---------- offset check ----------


def download_roads(bbox_wgs84: BBox, out: Path) -> Path:
    """Cache Overture road segments for the box (used only to find intersections)."""
    if out.exists():
        return out
    from overturemaps import core

    gdf = core.geodataframe("segment", bbox=bbox_wgs84)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    if "subtype" in gdf:
        gdf = gdf[gdf["subtype"] == "road"]
    keep = [c for c in ("id", "class", "geometry") if c in gdf]
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf[keep].to_parquet(out)
    return out


def find_intersections(
    roads: gpd.GeoDataFrame, aoi: BBox, n: int | None = None
) -> gpd.GeoDataFrame:
    """Order road intersections inside the box by farthest-point sampling.

    An intersection is a node where 3+ segment ends meet and at least 2 of them belong to
    an established road class (:data:`STABLE_ROAD_CLASSES`). New subdivision streets are
    mostly ``residential``/``service``, so this keeps points that existed in both years.

    Args:
        roads: Road line segments in the working CRS (optional ``class`` column).
        aoi: Study box in the working CRS.
        n: Number of points to return; None returns every candidate in spread order.

    Returns:
        Points with ``point_id``, the first ones spread out from the box center.
    """
    ends: list[tuple[tuple[int, int], bool]] = []
    classes = roads["class"] if "class" in roads else pd.Series("primary", index=roads.index)
    for geom, cls in zip(roads.geometry, classes, strict=True):
        stable = str(cls) in STABLE_ROAD_CLASSES
        for line in getattr(geom, "geoms", [geom]):
            cs = list(line.coords)
            for x, y in (cs[0][:2], cs[-1][:2]):
                ends.append(((round(x), round(y)), stable))
    df = pd.DataFrame(ends, columns=["xy", "stable"])
    agg = df.groupby("xy")["stable"].agg(["size", "sum"])
    nodes = [Point(xy) for xy, r in agg.iterrows() if r["size"] >= 3 and r["sum"] >= 2]
    inner = box(*aoi).buffer(-EDGE_MARGIN_M)
    cand = [pt for pt in nodes if inner.contains(pt)]
    want = len(cand) if n is None else n
    if len(cand) < want or not cand:
        raise ValueError(f"only {len(cand)} road intersections found inside the box")
    xy = np.array([(pt.x, pt.y) for pt in cand])
    center = np.array(inner.centroid.coords[0])
    chosen = [int(np.argmin(((xy - center) ** 2).sum(1)))]
    dist = ((xy - xy[chosen[0]]) ** 2).sum(1)
    while len(chosen) < want:
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, ((xy - xy[nxt]) ** 2).sum(1))
    return gpd.GeoDataFrame(
        {"point_id": [f"X{i + 1}" for i in range(want)]},
        geometry=[cand[i] for i in chosen],
        crs=roads.crs,
    )


def _gray_chip(path: Path, pt: Point, half_m: float) -> np.ndarray:
    """Read a grayscale (mean RGB) square chip centered on ``pt``."""
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(path) as src:
        win = (
            from_bounds(
                pt.x - half_m,
                pt.y - half_m,
                pt.x + half_m,
                pt.y + half_m,
                transform=src.transform,
            )
            .round_offsets()
            .round_lengths()
        )
        arr = src.read([1, 2, 3], window=win).astype("float32")
    return np.asarray(arr.mean(axis=0))


def phase_correlation_shift(
    a: np.ndarray, b: np.ndarray, upsample: int = 10
) -> tuple[float, float]:
    """Estimate the (row, col) shift in pixels that moves ``b`` onto ``a``.

    Uses scikit-image's sub-pixel phase correlation when available, otherwise a plain
    FFT phase correlation with integer precision.
    """
    try:
        from skimage.registration import phase_cross_correlation

        shift, _, _ = phase_cross_correlation(a, b, upsample_factor=upsample, normalization=None)
        return float(shift[0]), float(shift[1])
    except ImportError:
        win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
        fa, fb = np.fft.fft2(a * win), np.fft.fft2(b * win)
        r = fa * np.conj(fb)
        corr = np.abs(np.fft.ifft2(r / (np.abs(r) + 1e-9)))
        dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
        dy = dy - a.shape[0] if dy > a.shape[0] // 2 else dy
        dx = dx - a.shape[1] if dx > a.shape[1] // 2 else dx
        return float(dy), float(dx)


def chip_shift(before: Path, after: Path, pt: Point, res: float) -> dict[str, float]:
    """Estimate the offset at one point and how well the two chips match after shifting."""
    a = _gray_chip(before, pt, CHIP_HALF_M)
    b = _gray_chip(after, pt, CHIP_HALF_M)
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a, b = a[:h, :w], b[:h, :w]
    dy, dx = phase_correlation_shift(a, b)
    iy, ix = round(dy), round(dx)
    bs = np.roll(b, (iy, ix), axis=(0, 1))
    m = max(abs(iy), abs(ix)) + 1
    corr = float(np.corrcoef(a[m:-m, m:-m].ravel(), bs[m:-m, m:-m].ravel())[0, 1])
    dx_m, dy_m = dx * res, -dy * res
    return {
        "dx_m": round(dx_m, 2),
        "dy_m": round(dy_m, 2),
        "offset_m": round(math.hypot(dx_m, dy_m), 2),
        "correlation": round(corr, 3),
    }


def measure_offset(before: Path, after: Path, points: gpd.GeoDataFrame) -> pd.DataFrame:
    """Automatically estimate the Before/After offset at each check point.

    This is a provisional stand-in for the owner's QGIS measurement and uses the same
    points. Owner values in ``results/offset_measurements.csv`` always take priority.

    Args:
        before: Before mosaic.
        after: Aligned After mosaic.
        points: Check points from :func:`find_intersections`.

    Returns:
        One row per point with ``dx_m``, ``dy_m``, ``offset_m`` and ``correlation``.
    """
    import rasterio

    with rasterio.open(before) as src:
        res = src.res[0]
    rows = [
        {"point_id": pid, "x": pt.x, "y": pt.y, **chip_shift(before, after, pt, res)}
        for pid, pt in zip(points["point_id"], points.geometry, strict=True)
    ]
    return pd.DataFrame(rows)


def pick_check_points(
    before: Path, after: Path, candidates: gpd.GeoDataFrame, n: int
) -> gpd.GeoDataFrame:
    """Keep the first ``n`` spread-ordered candidates whose two chips really match."""
    scored = measure_offset(before, after, candidates)
    ok = scored[scored["correlation"] >= MIN_MATCH_CORRELATION].head(n)
    if len(ok) < n:
        raise ValueError(f"only {len(ok)} intersections look the same in both years")
    log.info(
        "check points: %d of %d candidates tested, kept %s",
        len(scored),
        len(candidates),
        ok["point_id"].tolist(),
    )
    pts = candidates.set_index("point_id").loc[ok["point_id"]].reset_index()
    pts["point_id"] = [f"X{i + 1}" for i in range(n)]
    return pts


def tolerance_from_offset(max_offset_m: float, cfg: Config) -> float:
    """Apply the locked rule: ``clamp(max_offset + 1.0, 3.0, 6.0)`` meters."""
    return float(min(max(max_offset_m + 1.0, 3.0), 6.0))


def write_offset_chips(before: Path, after: Path, points: gpd.GeoDataFrame, out_dir: Path) -> None:
    """Save side-by-side Before/After PNG chips with a crosshair and 10 m grid per point."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio
    from rasterio.windows import from_bounds

    out_dir.mkdir(parents=True, exist_ok=True)
    for pid, pt in zip(points["point_id"], points.geometry, strict=True):
        fig, axes = plt.subplots(1, 2, figsize=(10, 5.4), dpi=120)
        for ax, path, label in ((axes[0], before, "Before"), (axes[1], after, "After")):
            with rasterio.open(path) as src:
                h = CHIP_HALF_M
                win = from_bounds(pt.x - h, pt.y - h, pt.x + h, pt.y + h, transform=src.transform)
                rgb = np.moveaxis(src.read([1, 2, 3], window=win), 0, -1)
            ext = (-h, h, -h, h)
            ax.imshow(rgb, extent=ext)
            ax.axhline(0, color="#CC79A7", lw=0.8)
            ax.axvline(0, color="#CC79A7", lw=0.8)
            ax.set_xticks(np.arange(-h, h + 1, 10))
            ax.set_yticks(np.arange(-h, h + 1, 10))
            ax.grid(color="white", alpha=0.35, lw=0.5)
            ax.set_title(f"{label} · {pid} · E {pt.x:.1f} N {pt.y:.1f}", fontsize=9)
            ax.tick_params(labelsize=7)
        fig.suptitle("Offset check: meters from the crosshair. Imagery: USDA NAIP", fontsize=9)
        fig.tight_layout()
        fig.savefig(out_dir / f"{pid}.png")
        plt.close(fig)


def _owner_offsets(path: Path) -> pd.DataFrame | None:
    """Return owner-measured offsets if every row of the CSV has ``offset_m`` filled."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "offset_m" not in df or df["offset_m"].isna().any() or df.empty:
        return None
    return df


def offset_check(cfg: Config, *, force: bool = False) -> dict[str, Any]:
    """Pick check points, export chips, measure the offset and write the alignment report."""
    p = Paths(cfg.root)
    pts_path = p.offset_dir / "check_points.gpkg"
    if pts_path.exists() and not force:
        points = gpd.read_file(pts_path)
    else:
        roads = gpd.read_parquet(download_roads(cfg.aoi.bbox_wgs84, p.overture_roads))
        roads = roads.to_crs(cfg.aoi.working_crs)
        cand = find_intersections(roads, cfg.aoi.bbox_utm17n)
        n = cfg.change.offset_check_points
        points = pick_check_points(p.naip_before, p.naip_after_aligned, cand.head(60), n)
        p.offset_dir.mkdir(parents=True, exist_ok=True)
        points.to_file(pts_path, layer="points", driver="GPKG")
        write_offset_chips(p.naip_before, p.naip_after_aligned, points, p.offset_dir)
    auto = measure_offset(p.naip_before, p.naip_after_aligned, points)
    if not p.offset_measurements.exists():
        auto[["point_id", "x", "y"]].assign(dx_m=None, dy_m=None, offset_m=None).to_csv(
            p.offset_measurements, index=False
        )
    owner = _owner_offsets(p.offset_measurements)
    used, source = (owner, "owner_qgis") if owner is not None else (auto, "auto_phase_correlation")
    max_off = float(used["offset_m"].max())
    report = {
        "source": source,
        "provisional": owner is None,
        "max_offset_m": round(max_off, 2),
        "match_tolerance_m": tolerance_from_offset(max_off, cfg),
        "rule": cfg.change.tolerance_rule,
        "points": used.to_dict(orient="records"),
        "auto_estimate": auto.to_dict(orient="records"),
    }
    p.alignment_report.write_text(json.dumps(report, indent=2), "utf-8")
    log.info(
        "offset (%s): max %.2f m -> tolerance %.2f m",
        source,
        max_off,
        report["match_tolerance_m"],
    )
    return report


def run(cfg: Config, *, force: bool = False) -> None:
    """Run every F2 preparation step for the config."""
    p = Paths(cfg.root)
    if force or not p.naip_before.exists():
        mosaic(p.naip_raw("before"), p.naip_before, cfg)
    if force or not p.naip_after_aligned.exists():
        tmp = p.processed / "naip_after_mosaic.tif"
        mosaic(p.naip_raw("after"), tmp, cfg)
        align_to(p.naip_before, tmp, p.naip_after_aligned)
        tmp.unlink()
    if force or not p.naip_before_matched.exists():
        match_histograms(p.naip_before, p.naip_after_aligned, p.naip_before_matched)
    if force or not p.parcels_clipped.exists() or not p.permits_clipped.exists():
        clip_vectors(cfg)
    offset_check(cfg, force=force)


def histogram_lut(src: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Return a 256-entry lookup table mapping ``src`` uint8 values onto ``ref``'s histogram."""
    s_cdf = np.cumsum(np.bincount(src.ravel(), minlength=256)).astype("float64")
    r_cdf = np.cumsum(np.bincount(ref.ravel(), minlength=256)).astype("float64")
    s_cdf /= s_cdf[-1]
    r_cdf /= r_cdf[-1]
    return np.interp(s_cdf, r_cdf, np.arange(256)).round().clip(0, 255).astype("uint8")


def match_histograms(src_path: Path, ref_path: Path, out: Path) -> Path:
    """Write ``src`` with each band histogram-matched to ``ref`` (detector input only).

    The pretrained detector is sensitive to brightness and contrast, and the 2018 NAIP is
    hazier than 2022. Matching makes the same model with the same settings see both years
    alike. This is input normalization, never differencing: change is still decided by
    comparing building objects.

    Args:
        src_path: Before mosaic.
        ref_path: Aligned After mosaic (same grid).
        out: Matched Before mosaic.

    Returns:
        ``out``.
    """
    import rasterio

    with rasterio.open(src_path) as src, rasterio.open(ref_path) as ref:
        profile = src.profile.copy()
        luts = [histogram_lut(src.read(b), ref.read(b)) for b in range(1, src.count + 1)]
        with rasterio.open(out, "w", **profile) as dst:
            for _, win in dst.block_windows(1):
                block = src.read(window=win)
                dst.write(np.stack([luts[i][block[i]] for i in range(src.count)]), window=win)
            dst.descriptions = src.descriptions
    log.info("histogram-matched %s to %s -> %s", src_path.name, ref_path.name, out.name)
    return out
