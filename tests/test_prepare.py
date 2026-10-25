"""Preparation helpers: grid snapping, tolerance rule, intersections, offsets, rasters."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from parcelwatch.config import Config
from parcelwatch.prepare import (
    align_to,
    find_intersections,
    jurisdiction_shares,
    mosaic,
    phase_correlation_shift,
    snap_bounds,
    tolerance_from_offset,
)


@pytest.mark.parametrize(
    ("offset", "tol"), [(0.4, 3.0), (2.0, 3.0), (2.6, 3.6), (4.9, 5.9), (8.0, 6.0)]
)
def test_tolerance_rule(cfg: Config, offset: float, tol: float) -> None:
    assert tolerance_from_offset(offset, cfg) == pytest.approx(tol)


def test_snap_bounds_expands_to_grid() -> None:
    t = from_origin(1000.0, 2000.0, 0.6, 0.6)
    x0, y0, x1, y1 = snap_bounds((1000.5, 1000.1, 1010.0, 1999.9), t)
    for v in (x0 - 1000.0, x1 - 1000.0, 2000.0 - y0, 2000.0 - y1):
        assert abs(v / 0.6 - round(v / 0.6)) < 1e-9
    assert x0 <= 1000.5 and x1 >= 1010.0 and y0 <= 1000.1 and y1 >= 1999.9


def test_find_intersections_picks_spread_crossings(cfg: Config) -> None:
    x0, y0, x1, y1 = cfg.aoi.bbox_utm17n
    # A 4 x 4 street grid inside the box; segments split at every crossing.
    xs = np.linspace(x0 + 500, x1 - 500, 4)
    ys = np.linspace(y0 + 500, y1 - 500, 4)
    segs = []
    for x in xs:
        segs += [LineString([(x, ys[i]), (x, ys[i + 1])]) for i in range(3)]
    for y in ys:
        segs += [LineString([(xs[i], y), (xs[i + 1], y)]) for i in range(3)]
    roads = gpd.GeoDataFrame(geometry=segs, crs=cfg.aoi.working_crs)
    pts = find_intersections(roads, cfg.aoi.bbox_utm17n, 5)
    assert len(pts) == 5 and pts["point_id"].tolist() == ["X1", "X2", "X3", "X4", "X5"]
    d = pts.geometry.apply(lambda p: pts.geometry.distance(p).replace(0, np.inf).min())
    assert d.min() > 1000  # well spread


def test_phase_correlation_recovers_shift() -> None:
    rng = np.random.default_rng(0)
    base = rng.random((160, 160)).astype("float32")
    k = np.ones(5) / 5  # box blur so the image has texture at several scales
    base = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 0, base)
    base = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, base)
    shifted = np.roll(base, (3, -4), axis=(0, 1))
    dy, dx = phase_correlation_shift(base[20:140, 20:140], shifted[20:140, 20:140])
    assert round(dy) == -3 and round(dx) == 4


def test_jurisdiction_shares(cfg: Config) -> None:
    x0, y0, x1, y1 = cfg.aoi.bbox_utm17n
    w = x1 - x0
    limits = gpd.GeoDataFrame(
        {"NAME": ["Wendell", "Knightdale", "Raleigh"]},
        geometry=[
            box(x0, y0, x0 + 0.13 * w, y1),
            box(x1 - 0.08 * w, y0, x1, y1),
            box(0, 0, 1, 1),
        ],
        crs=cfg.aoi.working_crs,
    )
    s = jurisdiction_shares(limits, cfg.aoi.bbox_utm17n)
    assert s["WENDELL"] == pytest.approx(13.0, abs=0.1)
    assert s["KNIGHTDALE"] == pytest.approx(8.0, abs=0.1)
    assert s["unincorporated"] == pytest.approx(79.0, abs=0.2)
    assert "RALEIGH" not in s


def _tile(path: Path, x: float, y: float, value: int, cfg: Config, n: int = 40) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=n,
        height=n,
        count=4,
        dtype="uint8",
        crs=cfg.aoi.working_crs,
        transform=from_origin(x, y, 0.6, 0.6),
    ) as dst:
        dst.write(np.full((4, n, n), value, dtype="uint8"))


def test_mosaic_and_align(tmp_path: Path, cfg: Config) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    x0, _, _, y1 = cfg.aoi.bbox_utm17n
    _tile(raw / "a.tif", x0 - 3, y1 + 3, 10, cfg)
    _tile(raw / "b.tif", x0 - 3 + 24, y1 + 3, 20, cfg)
    small = cfg.model_copy(
        update={"aoi": cfg.aoi.model_copy(update={"bbox_utm17n": (x0, y1 - 15, x0 + 40, y1)})}
    )
    out = mosaic(raw, tmp_path / "before.tif", small)
    with rasterio.open(out) as src:
        assert src.count == 4 and src.res == pytest.approx((0.6, 0.6))
        assert src.crs == cfg.aoi.working_crs
        data = src.read(1)
        assert set(np.unique(data)) <= {10, 20}
        ref_shape, ref_transform = src.shape, src.transform
    aligned = align_to(out, raw / "b.tif", tmp_path / "after.tif")
    with rasterio.open(aligned) as src:
        assert src.shape == ref_shape and src.transform == ref_transform
