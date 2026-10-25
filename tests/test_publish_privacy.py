"""Privacy gate (TRD section 8): public files never carry parcel IDs, owners, addresses
or hexes with fewer than the minimum parcels. Fails the build if web/data breaks a rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcelwatch.config import Config
from parcelwatch.publish import audit_public_outputs
from tests.conftest import REPO_ROOT


def _hexes(*props: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": p, "geometry": None} for p in props],
    }


GOOD_HEX = {
    "h3": "892a8b5a1abffff",
    "n_parcels": 12,
    "n_changed": 3,
    "n_flagged": 1,
    "added_sqft": 400,
}


def test_real_public_folder_is_clean(cfg: Config) -> None:
    """The actual web/data folder must pass. Runs on every CI push."""
    problems = audit_public_outputs(REPO_ROOT / "web" / "data", cfg.privacy.min_parcels_per_hex)
    assert problems == []


def test_clean_files_pass(tmp_path: Path) -> None:
    (tmp_path / "changes_h3.geojson").write_text(json.dumps(_hexes(GOOD_HEX)))
    (tmp_path / "changes_h3.pmtiles").write_bytes(b"PMTiles")
    (tmp_path / "stats.json").write_text(json.dumps({"n_flagged": 3, "generated_at": "2026-10-25"}))
    assert audit_public_outputs(tmp_path, 5) == []


def test_missing_folder_passes(tmp_path: Path) -> None:
    assert audit_public_outputs(tmp_path / "nope", 5) == []


@pytest.mark.parametrize(
    "key", ["parcel_id", "PIN_NUM", "PIN", "OWNER", "owner_name", "ADDR1", "address"]
)
def test_forbidden_keys_fail(tmp_path: Path, key: str) -> None:
    (tmp_path / "changes_h3.geojson").write_text(json.dumps(_hexes({**GOOD_HEX, key: "x"})))
    assert any("forbidden key" in p for p in audit_public_outputs(tmp_path, 5))


def test_pin_like_value_fails(tmp_path: Path) -> None:
    (tmp_path / "stats.json").write_text(json.dumps({"note": "see 1234567890"}))
    assert any("PIN" in p for p in audit_public_outputs(tmp_path, 5))


def test_small_hex_fails(tmp_path: Path) -> None:
    (tmp_path / "changes_h3.geojson").write_text(json.dumps(_hexes({**GOOD_HEX, "n_parcels": 4})))
    assert any("n_parcels=4" in p for p in audit_public_outputs(tmp_path, 5))


def test_pmtiles_without_source_fails(tmp_path: Path) -> None:
    (tmp_path / "changes_h3.pmtiles").write_bytes(b"PMTiles")
    assert any("no source" in p for p in audit_public_outputs(tmp_path, 5))


def test_other_file_types_fail(tmp_path: Path) -> None:
    (tmp_path / "parcels.csv").write_text("parcel_id\n1\n")
    assert any("not allowed" in p for p in audit_public_outputs(tmp_path, 5))
