"""Scaffold sanity: the synthetic fixture is valid and repo rules hold in source code."""

from __future__ import annotations

import geopandas as gpd

from parcelwatch.config import Config
from tests.conftest import REPO_ROOT


def test_tiny_scene_is_in_working_crs_and_box(
    cfg: Config, tiny_scene: dict[str, gpd.GeoDataFrame]
) -> None:
    min_x, min_y, max_x, max_y = cfg.aoi.bbox_utm17n
    for name, gdf in tiny_scene.items():
        assert gdf.crs == cfg.aoi.working_crs, name
        assert gdf.is_valid.all(), name
        x0, y0, x1, y1 = gdf.total_bounds
        assert min_x <= x0 and x1 <= max_x and min_y <= y0 and y1 <= max_y, name
    assert tiny_scene["before"].area.tolist() == [100.0, 100.0]


def test_no_wake_server_urls_in_source() -> None:
    """Rule 5: the only mention of Wake's own server is the http.py block list."""
    for path in (REPO_ROOT / "src" / "parcelwatch").rglob("*.py"):
        if path.name in {"http.py", "config.py"}:
            continue
        text = path.read_text("utf-8")
        assert "maps.wake.gov" not in text and "maps.wakegov.com" not in text, path
