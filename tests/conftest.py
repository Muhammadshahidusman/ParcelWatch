"""Shared pytest fixtures: the real config, a temp project root and a tiny synthetic scene.

Everything here is built in memory with shapely: no network, no GPU, no data/ files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from parcelwatch.config import Config, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "configs" / "wake_pilot.yaml"


@pytest.fixture(scope="session")
def cfg() -> Config:
    """The real pilot config."""
    return load_config(CONFIG_PATH)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A throwaway project root holding a copy of the pilot config at ``configs/``."""
    (tmp_path / "configs").mkdir()
    shutil.copy(CONFIG_PATH, tmp_path / "configs" / "wake_pilot.yaml")
    return tmp_path


@pytest.fixture
def tiny_scene(cfg: Config) -> dict[str, gpd.GeoDataFrame]:
    """A tiny synthetic scene in the working CRS, inside the study box.

    Three 30 x 30 m parcels in a row. Parcel A keeps a 10 x 10 m house; parcel B gets a new
    10 x 10 m house; parcel C's 10 x 10 m shed is demolished. One permit sits inside B.
    """
    x0, y0 = cfg.aoi.bbox_utm17n[0] + 100.0, cfg.aoi.bbox_utm17n[1] + 100.0
    crs = cfg.aoi.working_crs
    parcels = gpd.GeoDataFrame(
        {"PIN_NUM": ["0000000001", "0000000002", "0000000003"], "CITY_DECODE": ["", "", ""]},
        geometry=[box(x0 + i * 30, y0, x0 + (i + 1) * 30, y0 + 30) for i in range(3)],
        crs=crs,
    )
    before = gpd.GeoDataFrame(
        geometry=[box(x0 + 10, y0 + 10, x0 + 20, y0 + 20), box(x0 + 70, y0 + 10, x0 + 80, y0 + 20)],
        crs=crs,
    )
    after = gpd.GeoDataFrame(
        geometry=[box(x0 + 10, y0 + 10, x0 + 20, y0 + 20), box(x0 + 40, y0 + 10, x0 + 50, y0 + 20)],
        crs=crs,
    )
    permits = gpd.GeoDataFrame(
        {"PERMIT_NUMBER": ["P1"], "PIN": ["0000000002"]},
        geometry=[Point(x0 + 45, y0 + 25)],
        crs=crs,
    )
    return {"parcels": parcels, "before": before, "after": after, "permits": permits}
