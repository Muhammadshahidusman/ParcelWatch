"""Loaders: parcels drop owner/address on read and land in EPSG:26917; permits filter right."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from pyproj import Transformer
from shapely.geometry import box

from parcelwatch.config import Config
from parcelwatch.download import (
    download_hub_file,
    load_parcels,
    load_permits,
    transform_bbox,
)


@pytest.fixture
def parcel_zip(tmp_path: Path, cfg: Config) -> Path:
    """Three parcels in EPSG:2264: one inside the box, one on its edge, one far away."""
    x0, y0, _x1, _y1 = cfg.aoi.bbox_utm17n
    geoms = [
        box(x0 + 100, y0 + 100, x0 + 130, y0 + 130),  # inside
        box(x0 - 20, y0 + 200, x0 + 20, y0 + 240),  # straddles the west edge
        box(x0 - 5000, y0, x0 - 4970, y0 + 30),  # far outside
    ]
    gdf = gpd.GeoDataFrame(
        {
            "PIN_NUM": ["1111111111", "2222222222", "3333333333"],
            "OWNER": ["A", "B", "C"],
            "ADDR1": ["1 Main"] * 3,
            "ADDR2": [""] * 3,
            "ADDR3": [""] * 3,
            "BLDG_VAL": [100000, 0, 5],
            "CITY_DECODE": ["WENDELL", "", ""],
        },
        geometry=geoms,
        crs=cfg.aoi.working_crs,
    ).to_crs(cfg.vectors.parcels_source_crs)
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf.to_file(shp_dir / "Parcels.shp")
    zpath = tmp_path / "parcels.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f.name)
    return zpath


def test_load_parcels_drops_private_columns_and_reprojects(parcel_zip: Path, cfg: Config) -> None:
    gdf = load_parcels(parcel_zip, cfg.aoi.bbox_utm17n, cfg)
    assert gdf.crs == cfg.aoi.working_crs
    assert not {"OWNER", "ADDR1", "ADDR2", "ADDR3"} & set(gdf.columns)
    assert sorted(gdf["PIN_NUM"]) == ["1111111111", "2222222222"]
    assert "CITY_DECODE" in gdf.columns  # restored from the shapefile's CITY_DECOD
    assert "BLDG_VAL" in gdf.columns
    assert gdf.is_valid.all()
    inside = gdf.set_index("PIN_NUM")
    assert bool(inside.loc["1111111111", "in_box"]) is True
    assert inside.loc["1111111111"].geometry.area == pytest.approx(900, rel=1e-3)


def _permit_csv(tmp_path: Path, cfg: Config) -> Path:
    x0, y0, _, _ = cfg.aoi.bbox_utm17n
    to_ll = Transformer.from_crs(cfg.aoi.working_crs, "EPSG:4326", always_xy=True)
    lon_in, lat_in = to_ll.transform(x0 + 115, y0 + 115)
    lon_out, lat_out = to_ll.transform(x0 - 5000, y0)
    rows = [
        # id, pin, date, type, lon, lat
        (
            "P1",
            "1111111111",
            "2019/05/01 00:00:00+00",
            "Residential Building",
            lon_in,
            lat_in,
        ),
        (
            "P2",
            "1111111111",
            "2017/10/21 00:00:00+00",
            "Residential Building",
            lon_in,
            lat_in,
        ),
        (
            "P3",
            "1111111111",
            "2022/10/06 00:00:00+00",
            "Demolition Permit",
            lon_in,
            lat_in,
        ),
        ("P4", "1111111111", "2020/01/01 00:00:00+00", "Plumbing", lon_in, lat_in),
        (
            "P5",
            "9999999999",
            "2020/01/01 00:00:00+00",
            "Residential Building",
            lon_out,
            lat_out,
        ),
        (
            "P6",
            "2222222222",
            "2020/01/01 00:00:00+00",
            "Residential Building",
            None,
            None,
        ),
        ("P7", "1111111111", "not a date", "Residential Building", lon_in, lat_in),
    ]
    f = cfg.fields
    cols = [
        f.permit_id,
        f.permit_parcel_id,
        f.permit_issue_date,
        f.permit_type,
        f.permit_x,
        f.permit_y,
    ]
    path = tmp_path / "permits.csv"
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return path


def test_load_permits_window_types_and_box(tmp_path: Path, cfg: Config) -> None:
    window = (cfg.permits.window_start, cfg.permits.window_end)
    gdf = load_permits(_permit_csv(tmp_path, cfg), cfg.aoi.bbox_utm17n, window, cfg)
    # P1 in window; P2 a day early; P3 on the end date (inclusive); P4 wrong type;
    # P5 outside box; P6 no coordinates; P7 unparseable date.
    assert sorted(gdf["PERMIT_NUMBER"]) == ["P1", "P3"]
    assert gdf.crs == cfg.aoi.working_crs
    assert gdf["issue_date"].min() >= date(2017, 10, 22)


def test_load_permits_keeps_pin_matches_without_points(tmp_path: Path, cfg: Config) -> None:
    window = (cfg.permits.window_start, cfg.permits.window_end)
    gdf = load_permits(
        _permit_csv(tmp_path, cfg),
        cfg.aoi.bbox_utm17n,
        window,
        cfg,
        pins={"2222222222"},
    )
    assert sorted(gdf["PERMIT_NUMBER"]) == ["P1", "P3", "P6"]
    assert not bool(gdf.set_index("PERMIT_NUMBER").loc["P6", "in_box"])


def test_transform_bbox_encloses_box(cfg: Config) -> None:
    ll = transform_bbox(cfg.aoi.bbox_utm17n, cfg.aoi.working_crs, "EPSG:4326")
    w = cfg.aoi.bbox_wgs84
    # The UTM box was derived from the WGS84 box, so they agree to ~0.001 degrees.
    assert all(abs(a - b) < 2e-3 for a, b in zip(ll, w, strict=True))


def test_download_hub_file_skips_existing(tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    out.write_text("cached")
    # Would raise on the blocked host if it tried to fetch.
    assert download_hub_file("https://maps.wake.gov/x", out) == out
    assert out.read_text() == "cached"


def test_restore_names_skips_ambiguous() -> None:
    from parcelwatch.download import restore_shapefile_names

    cols = ["PIN_NUM", "CITY_DECOD", "LAND_CLASS", "LAND_CLA_1", "TOTAL_VALU"]
    wanted = ["PIN_NUM", "CITY_DECODE", "LAND_CLASS_DECODE", "TOTAL_VALUE_ASSD"]
    assert restore_shapefile_names(cols, wanted) == {
        "CITY_DECOD": "CITY_DECODE",
        "TOTAL_VALU": "TOTAL_VALUE_ASSD",
    }


def test_load_parcels_reads_only_allowed_fields(parcel_zip: Path, cfg: Config) -> None:
    gdf = load_parcels(parcel_zip, cfg.aoi.bbox_utm17n, cfg)
    assert set(gdf.columns) <= {"PIN_NUM", "BLDG_VAL", "CITY_DECODE", "geometry", "in_box"}
