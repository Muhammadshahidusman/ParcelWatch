"""Change classification, parcel roll-up and permit check (TRD section 3.1), test-first."""

from __future__ import annotations

from datetime import date

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from parcelwatch.changes import (
    attach_permits,
    classify_changes,
    combine_changes,
    rollup_to_parcels,
)
from parcelwatch.config import Config

CRS = "EPSG:26917"
X0, Y0 = 729000.0, 3958000.0


def sq(x: float, y: float, w: float, h: float | None = None) -> box:
    """Axis-aligned rectangle with its lower-left corner at (X0 + x, Y0 + y)."""
    return box(X0 + x, Y0 + y, X0 + x + w, Y0 + y + (h if h is not None else w))


def gdf(geoms: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=geoms, crs=CRS)


def labels(after: gpd.GeoDataFrame) -> list[str]:
    return after["change"].tolist()


# ---------- classify_changes ----------


def test_grow_100_to_130_is_expanded(cfg: Config) -> None:
    after, demo = classify_changes(gdf([sq(0, 0, 10)]), gdf([sq(0, 0, 13, 10)]), cfg, 3.0)
    assert labels(after) == ["expanded"]
    assert after["added_m2"].iloc[0] == pytest.approx(30.0)
    assert after["matched_before_m2"].iloc[0] == pytest.approx(100.0)
    assert demo.empty


def test_grow_100_to_115_is_unchanged(cfg: Config) -> None:
    after, _ = classify_changes(gdf([sq(0, 0, 10)]), gdf([sq(0, 0, 11.5, 10)]), cfg, 3.0)
    assert labels(after) == ["unchanged"]
    assert after["added_m2"].iloc[0] == 0.0


def test_big_building_needs_ratio_too(cfg: Config) -> None:
    # 500 -> 540 m2 adds 40 m2 (>= 20) but ratio 1.08 < 1.2, so unchanged.
    after, _ = classify_changes(gdf([sq(0, 0, 50, 10)]), gdf([sq(0, 0, 54, 10)]), cfg, 3.0)
    assert labels(after) == ["unchanged"]


def test_small_building_needs_absolute_gain_too(cfg: Config) -> None:
    # 12 -> 24 m2 doubles (ratio 2.0) but adds only 12 m2 (< 20), so unchanged.
    after, _ = classify_changes(gdf([sq(0, 0, 4, 3)]), gdf([sq(0, 0, 8, 3)]), cfg, 3.0)
    assert labels(after) == ["unchanged"]


def test_new_building_far_from_any_before(cfg: Config) -> None:
    after, _ = classify_changes(gdf([sq(0, 0, 10)]), gdf([sq(0, 0, 10), sq(100, 0, 12)]), cfg, 3.0)
    assert labels(after) == ["unchanged", "new"]
    assert after["added_m2"].tolist() == pytest.approx([0.0, 144.0])
    assert after["matched_before_m2"].isna().tolist() == [False, True]


def test_shift_within_tolerance_still_matches(cfg: Config) -> None:
    # Same house, After image shifted 2.5 m east; edge gap 0 < 3 m so it matches.
    after, demo = classify_changes(gdf([sq(0, 0, 10)]), gdf([sq(12.5, 0, 10)]), cfg, 3.0)
    assert labels(after) == ["unchanged"]
    assert demo.empty


def test_gap_beyond_tolerance_is_new_plus_demolished(cfg: Config) -> None:
    # 4 m gap between edges, tolerance 3 m: no match either way.
    after, demo = classify_changes(gdf([sq(0, 0, 10)]), gdf([sq(14, 0, 10)]), cfg, 3.0)
    assert labels(after) == ["new"]
    assert len(demo) == 1 and demo["change"].iloc[0] == "demolished"


def test_tolerance_argument_is_used(cfg: Config) -> None:
    after, demo = classify_changes(gdf([sq(0, 0, 10)]), gdf([sq(14, 0, 10)]), cfg, 5.0)
    assert labels(after) == ["unchanged"]
    assert demo.empty


def test_demolished(cfg: Config) -> None:
    after, demo = classify_changes(
        gdf([sq(0, 0, 10), sq(200, 0, 8)]), gdf([sq(0, 0, 10)]), cfg, 3.0
    )
    assert labels(after) == ["unchanged"]
    assert demo["area_m2"].tolist() == pytest.approx([64.0])
    assert demo["year"].tolist() == [cfg.imagery.before.year]
    assert demo["added_m2"].tolist() == [0.0]


def test_tiny_buildings_dropped_both_years(cfg: Config) -> None:
    # 9 m2 shed disappears and a 9 m2 blob appears: both below 10 m2, so no change at all.
    after, demo = classify_changes(gdf([sq(0, 0, 3)]), gdf([sq(100, 0, 3)]), cfg, 3.0)
    assert after.empty and demo.empty


def test_two_before_merge_into_one_after(cfg: Config) -> None:
    # Two 50 m2 buildings joined by an addition into one 150 m2 building: matched 100, +50.
    before = gdf([sq(0, 0, 5, 10), sq(10, 0, 5, 10)])
    after, demo = classify_changes(before, gdf([sq(0, 0, 15, 10)]), cfg, 3.0)
    assert labels(after) == ["expanded"]
    assert after["matched_before_m2"].iloc[0] == pytest.approx(100.0)
    assert after["added_m2"].iloc[0] == pytest.approx(50.0)
    assert demo.empty


def test_output_schema(cfg: Config) -> None:
    after, demo = classify_changes(
        gdf([sq(0, 0, 10), sq(300, 0, 10)]), gdf([sq(0, 0, 10)]), cfg, 3.0
    )
    cols = {
        "bldg_id",
        "year",
        "change",
        "area_m2",
        "matched_before_m2",
        "added_m2",
        "model",
        "score",
    }
    assert cols <= set(after.columns) and cols <= set(demo.columns)
    assert after["bldg_id"].iloc[0] == f"{cfg.imagery.after.year}_0"
    assert demo["bldg_id"].iloc[0] == f"{cfg.imagery.before.year}_1"
    assert after.crs == CRS
    assert (after["added_m2"] >= 0).all()


def test_rejects_wrong_crs(cfg: Config) -> None:
    wrong = gdf([sq(0, 0, 10)]).to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="EPSG:26917"):
        classify_changes(wrong, gdf([sq(0, 0, 10)]), cfg, 3.0)


# ---------- rollup_to_parcels ----------


@pytest.fixture
def parcels() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"PIN_NUM": ["A", "B", "C"], "CITY_DECODE": ["WENDELL", "", "KNIGHTDALE"]},
        geometry=[sq(0, 0, 50), sq(50, 0, 50), sq(100, 0, 50)],
        crs=CRS,
    )


def test_rollup_counts_and_area(cfg: Config, parcels: gpd.GeoDataFrame) -> None:
    before = gdf([sq(10, 10, 10), sq(110, 10, 10)])
    after = gdf([sq(10, 10, 13, 10), sq(60, 10, 10), sq(70, 30, 5, 4)])
    a, d = classify_changes(before, after, cfg, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), parcels, cfg)
    pc = pc.set_index("parcel_id")
    assert set(pc.index) == {"A", "B", "C"}
    assert pc.loc["A", ["n_new", "n_expanded", "n_demolished"]].tolist() == [0, 1, 0]
    assert pc.loc["B", ["n_new", "n_expanded", "n_demolished"]].tolist() == [2, 0, 0]
    assert pc.loc["C", ["n_new", "n_expanded", "n_demolished"]].tolist() == [0, 0, 1]
    assert pc.loc["B", "added_m2"] == pytest.approx(120.0)
    assert pc.loc["B", "added_sqft"] == pytest.approx(120.0 * 10.764)
    assert pc.loc["A", "added_m2"] == 0.0  # expanded doesn't count: flags are new-only
    assert pc.loc["C", "added_m2"] == 0.0
    assert pc.loc["A", "city"] == "WENDELL"
    assert pc.crs == CRS


def with_flag_types(cfg: Config, kinds: list[str]) -> Config:
    """The pilot config with a different ``change.flag_change_types``."""
    return cfg.model_copy(
        update={"change": cfg.change.model_copy(update={"flag_change_types": kinds})}
    )


def test_rollup_added_area_follows_flag_change_types(
    cfg: Config, parcels: gpd.GeoDataFrame
) -> None:
    every = with_flag_types(cfg, ["new", "expanded", "demolished"])
    a, d = classify_changes(gdf([sq(10, 10, 10)]), gdf([sq(10, 10, 13, 10)]), every, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), parcels, every).set_index("parcel_id")
    assert pc.loc["A", "added_m2"] == pytest.approx(30.0)


def test_rollup_building_on_boundary_goes_to_one_parcel(
    cfg: Config, parcels: gpd.GeoDataFrame
) -> None:
    # New 20 x 10 building straddling the A/B line, mostly in B.
    a, d = classify_changes(gdf([]), gdf([sq(45, 10, 20, 10)]), cfg, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), parcels, cfg)
    assert pc["n_new"].sum() == 1
    assert len(pc) == 1


def test_rollup_skips_unchanged_and_logs_orphans(
    cfg: Config, parcels: gpd.GeoDataFrame, caplog: pytest.LogCaptureFixture
) -> None:
    a, d = classify_changes(
        gdf([sq(10, 10, 10)]), gdf([sq(10, 10, 10), sq(500, 500, 10)]), cfg, 3.0
    )
    pc = rollup_to_parcels(combine_changes(a, d), parcels, cfg)
    assert pc.empty
    assert "orphan" in caplog.text


# ---------- attach_permits ----------


def _permits(cfg: Config, rows: list[tuple]) -> gpd.GeoDataFrame:
    f = cfg.fields
    return gpd.GeoDataFrame(
        {
            f.permit_id: [r[0] for r in rows],
            f.permit_parcel_id: [r[1] for r in rows],
            "issue_date": [r[2] for r in rows],
            f.permit_type: [r[3] for r in rows],
        },
        geometry=[r[4] for r in rows],
        crs=CRS,
    )


def test_attach_permits_spatial_or_pin(cfg: Config, parcels: gpd.GeoDataFrame) -> None:
    a, d = classify_changes(gdf([sq(110, 10, 10)]), gdf([sq(10, 10, 10), sq(60, 10, 10)]), cfg, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), parcels, cfg)
    rb = "Residential Building"
    permits = _permits(
        cfg,
        [
            ("P1", "", date(2019, 1, 1), rb, Point(X0 + 25, Y0 + 25)),  # in A spatially
            ("P2", "B", date(2020, 1, 1), rb, None),  # B by PIN only
            (
                "P3",
                "B",
                date(2020, 1, 1),
                rb,
                Point(X0 + 75, Y0 + 25),
            ),  # B both ways: count once
            (
                "P4",
                "C",
                date(2016, 1, 1),
                rb,
                Point(X0 + 125, Y0 + 25),
            ),  # C, before window
            (
                "P5",
                "C",
                date(2020, 1, 1),
                "Plumbing",
                Point(X0 + 125, Y0 + 25),
            ),  # C, wrong type
        ],
    )
    window = (cfg.permits.window_start, cfg.permits.window_end)
    out = attach_permits(pc, permits, window, cfg).set_index("parcel_id")
    assert out.loc["A", "n_permits"] == 1
    assert out.loc["B", "n_permits"] == 2
    assert out.loc["C", "n_permits"] == 0
    # C is demolished only: no permit, but flags need a new building (pilot config)
    assert out["flag_unpermitted"].to_dict() == {"A": False, "B": False, "C": False}
    every = with_flag_types(cfg, ["new", "expanded", "demolished"])
    out = attach_permits(pc, permits, window, every).set_index("parcel_id")
    assert out["flag_unpermitted"].to_dict() == {"A": False, "B": False, "C": True}


def test_attach_permits_flags_only_flag_change_types(
    cfg: Config, parcels: gpd.GeoDataFrame
) -> None:
    before = gdf([sq(10, 10, 10), sq(110, 10, 10)])
    after = gdf([sq(10, 10, 13, 10), sq(60, 10, 10)])  # A expanded, B new, C demolished
    a, d = classify_changes(before, after, cfg, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), parcels, cfg)
    window = (cfg.permits.window_start, cfg.permits.window_end)
    out = attach_permits(pc, _permits(cfg, []), window, cfg).set_index("parcel_id")
    assert out["flag_unpermitted"].to_dict() == {"A": False, "B": True, "C": False}


def test_attach_permits_empty(cfg: Config, parcels: gpd.GeoDataFrame) -> None:
    a, d = classify_changes(gdf([]), gdf([sq(10, 10, 10)]), cfg, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), parcels, cfg)
    window = (cfg.permits.window_start, cfg.permits.window_end)
    out = attach_permits(pc, _permits(cfg, []), window, cfg)
    assert out["n_permits"].tolist() == [0]
    assert out["flag_unpermitted"].tolist() == [True]


def test_tiny_scene_end_to_end(cfg: Config, tiny_scene: dict[str, gpd.GeoDataFrame]) -> None:
    s = tiny_scene
    a, d = classify_changes(s["before"], s["after"], cfg, 3.0)
    pc = rollup_to_parcels(combine_changes(a, d), s["parcels"], cfg)
    permits = s["permits"].assign(issue_date=date(2020, 1, 1), PERMIT_TYPE="Residential Building")
    out = attach_permits(pc, permits, (cfg.permits.window_start, cfg.permits.window_end), cfg)
    out = out.set_index("parcel_id")
    assert out.loc["0000000002", "n_new"] == 1 and not out.loc["0000000002", "flag_unpermitted"]
    assert out.loc["0000000003", "n_demolished"] == 1
    assert not out.loc["0000000003", "flag_unpermitted"]  # demolished only isn't flagged
    assert "0000000001" not in out.index
