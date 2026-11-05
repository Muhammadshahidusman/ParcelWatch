"""The config loader validates the pilot YAML and rejects bad values."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from parcelwatch.config import Config, load_config
from tests.conftest import CONFIG_PATH


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(data), "utf-8")
    return p


@pytest.fixture
def raw() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text("utf-8"))


def test_pilot_config_matches_locked_decisions(cfg: Config) -> None:
    """Spot-check locked config values."""
    assert cfg.aoi.bbox_wgs84 == (-78.4766, 35.7337, -78.4211, 35.7787)
    assert cfg.aoi.bbox_utm17n == (728214, 3957349, 733103, 3962472)
    assert cfg.aoi.working_crs == "EPSG:26917"
    assert cfg.imagery.collection == "naip"
    assert cfg.imagery.before.date == date(2018, 10, 22)
    assert cfg.imagery.after.date == date(2022, 10, 6)
    assert len(cfg.imagery.before.items) == len(cfg.imagery.after.items) == 4
    assert cfg.permits.window_start == date(2017, 10, 22)
    assert cfg.permits.window_end == date(2022, 10, 6)
    assert cfg.fields.parcel_id == "PIN_NUM"
    assert set(cfg.fields.never_load) == {"OWNER", "ADDR1", "ADDR2", "ADDR3"}
    assert cfg.change.min_building_area_m2 == 10.0
    assert cfg.change.expanded_min_added_m2 == 20.0
    assert cfg.change.expanded_min_ratio == 1.2
    assert cfg.privacy.h3_resolution == 9
    assert cfg.privacy.min_parcels_per_hex == 5
    assert cfg.validation.random_state == 42


def test_load_records_hash_and_root(cfg: Config) -> None:
    assert cfg.sha256 is not None and len(cfg.sha256) == 64
    assert (cfg.root / "configs" / "wake_pilot.yaml").exists()


def test_municipal_rate_lookup(cfg: Config) -> None:
    v = cfg.valuation
    assert v.municipal_rate("WENDELL") == 42.0
    assert v.municipal_rate("knightdale ") == 44.0
    assert v.municipal_rate("") == 0.0
    assert v.municipal_rate(None) == 0.0


def test_unknown_key_rejected(tmp_path: Path, raw: dict) -> None:
    raw["change"]["min_bulding_area_m2"] = 5  # typo
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_wake_server_url_rejected(tmp_path: Path, raw: dict) -> None:
    raw["vectors"]["parcels_download"] = "https://maps.wake.gov/arcgis/rest/services/x"
    with pytest.raises(ValidationError, match="Wake"):
        load_config(_write(tmp_path, raw))


def test_area_must_match_box(tmp_path: Path, raw: dict) -> None:
    raw["aoi"]["area_km2"] = 20.1
    with pytest.raises(ValidationError, match="area_km2"):
        load_config(_write(tmp_path, raw))


def test_dates_must_be_ordered(tmp_path: Path, raw: dict) -> None:
    raw["permits"]["window_start"] = date(2023, 1, 1)
    with pytest.raises(ValidationError, match="window_start"):
        load_config(_write(tmp_path, raw))


def test_config_is_frozen(cfg: Config) -> None:
    with pytest.raises(ValidationError):
        cfg.change.match_tolerance_m = 9.0  # type: ignore[misc]
