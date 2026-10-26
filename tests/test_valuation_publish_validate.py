"""Money (TRD 3.1), H3 publishing and validation metrics, with hand-checked answers."""

from __future__ import annotations

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import box

from parcelwatch.config import Config
from parcelwatch.publish import audit_public_outputs, to_h3, write_stats
from parcelwatch.validate import compute_metrics, make_sample_sheet
from parcelwatch.valuation import estimate_missed_tax, value_per_sqft

CRS = "EPSG:26917"
X0, Y0 = 729000.0, 3958000.0


# ---------- valuation ----------


def _value_parcels(n: int, vpsf: float, year: int = 2022) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "BLDG_VAL": [vpsf * 2000] * n,
            "HEATEDAREA": [2000] * n,
            "YEAR_BUILT": [year] * n,
            "in_box": [True] * n,
        }
    )


def test_value_per_sqft_median_of_recent_builds(cfg: Config) -> None:
    recent = pd.concat([_value_parcels(20, 150), _value_parcels(15, 200)])
    old = _value_parcels(50, 50, year=1990)
    tiny = _value_parcels(5, 999).assign(HEATEDAREA=500, BLDG_VAL=999 * 500)
    zero = _value_parcels(5, 999).assign(BLDG_VAL=0)
    res = value_per_sqft(pd.concat([recent, old, tiny, zero]), cfg)
    assert res.value == pytest.approx(150.0)
    assert res.n == 35 and res.scope == "bbox"
    assert res.min_year_built == 2021


def test_value_per_sqft_falls_back_to_county(cfg: Config) -> None:
    box_parcels = _value_parcels(10, 150)
    county = pd.concat([_value_parcels(40, 180), box_parcels])
    res = value_per_sqft(box_parcels, cfg, county=county)
    assert res.scope == "county" and res.n == 50
    assert res.value == pytest.approx(180.0)
    with pytest.raises(ValueError, match="fewer than"):
        value_per_sqft(box_parcels, cfg)


def _pc() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": ["A", "B", "C", "D"],
            "city": ["WENDELL", "", "KNIGHTDALE", ""],
            "added_sqft": [1000.0, 500.0, 2000.0, 0.0],
            "flag_unpermitted": [True, True, False, True],
        },
        geometry=[box(X0 + i * 50, Y0, X0 + i * 50 + 40, Y0 + 40) for i in range(4)],
        crs=CRS,
    )


def test_estimate_missed_tax(cfg: Config) -> None:
    out, totals = estimate_missed_tax(_pc(), 0.75, cfg, vpsf=150.0)
    out = out.set_index("parcel_id")
    # A: 1000 sqft * $150 = $150,000; rate 53.71 + 42.00 = 95.71 c/$100 -> $1,435.65
    assert out.loc["A", "est_missed_value_usd"] == pytest.approx(150_000)
    assert out.loc["A", "est_yearly_tax_usd"] == pytest.approx(1435.65)
    # B: 500 * 150 = 75,000 at 53.71 -> $402.825
    assert out.loc["B", "est_yearly_tax_usd"] == pytest.approx(402.825)
    # C: Knightdale 97.71, not flagged
    assert out.loc["C", "est_yearly_tax_usd"] == pytest.approx(300_000 * 97.71 / 10_000)
    assert out.loc["A", "rank"] == 1 and out.loc["B", "rank"] == 2 and out.loc["D", "rank"] == 3
    assert pd.isna(out.loc["C", "rank"])
    assert (out["value_per_sqft"] == 150.0).all()
    assert totals["est_yearly_tax_usd_raw"] == pytest.approx(1435.65 + 402.825)
    assert totals["est_yearly_tax_usd_adjusted"] == pytest.approx((1435.65 + 402.825) * 0.75)
    assert totals["est_missed_value_usd_adjusted"] == pytest.approx(225_000 * 0.75)


def test_estimate_without_precision_leaves_adjusted_empty(cfg: Config) -> None:
    _, totals = estimate_missed_tax(_pc(), None, cfg, vpsf=150.0)
    assert totals["est_yearly_tax_usd_adjusted"] is None
    assert totals["est_yearly_tax_usd_raw"] > 0


# ---------- H3 publishing ----------


def _all_parcels(n: int, dx: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": [f"P{i}" for i in range(n)],
            "changed": [i % 2 == 0 for i in range(n)],
            "flag_unpermitted": [i % 4 == 0 for i in range(n)],
            "added_sqft": [430.0 if i % 4 == 0 else 0.0 for i in range(n)],
        },
        geometry=[box(X0 + i * dx, Y0, X0 + i * dx + 5, Y0 + 5) for i in range(n)],
        crs=CRS,
    )


def test_to_h3_aggregates_and_drops_small_hexes(cfg: Config) -> None:
    dense = _all_parcels(12, 6.0)  # 12 parcels in ~70 m: one or two res-9 hexes
    lonely = _all_parcels(2, 1.0).assign(parcel_id=["L0", "L1"])
    lonely["geometry"] = lonely.geometry.translate(3000, 3000)
    hexes = to_h3(pd.concat([dense, lonely], ignore_index=True), 9, 5)
    assert list(hexes.columns) == [
        "h3",
        "n_parcels",
        "n_changed",
        "n_flagged",
        "added_sqft",
        "geometry",
    ]
    assert hexes.crs == "EPSG:4326"
    assert (hexes["n_parcels"] >= 5).all()
    assert hexes["n_parcels"].sum() <= 12
    assert all(h3.get_resolution(c) == 9 for c in hexes["h3"])
    assert (hexes["added_sqft"] % 100 == 0).all()


def test_published_hexes_pass_privacy_audit(tmp_path, cfg: Config) -> None:  # type: ignore[no-untyped-def]
    hexes = to_h3(_all_parcels(40, 3.0), 9, 5)
    hexes.to_file(tmp_path / "changes_h3.geojson", driver="GeoJSON")
    write_stats(
        {"n_flagged": 10, "generated_at": "2026-10-26T00:00:00Z"},
        tmp_path / "stats.json",
    )
    assert audit_public_outputs(tmp_path, 5) == []


# ---------- validation ----------


def _sheet_inputs(n_flag: int, n_unch: int) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    n = n_flag + n_unch + 20
    parcels = gpd.GeoDataFrame(
        {"PIN_NUM": [f"{i:010d}" for i in range(n)], "in_box": True},
        geometry=[box(X0 + i * 40, Y0, X0 + i * 40 + 30, Y0 + 30) for i in range(n)],
        crs=CRS,
    )
    changed = parcels.iloc[: n_flag + 20].rename(columns={"PIN_NUM": "parcel_id"})
    pc = gpd.GeoDataFrame(
        {
            "parcel_id": changed["parcel_id"],
            "n_new": 1,
            "n_expanded": 0,
            "n_demolished": 0,
            "added_sqft": 1000.0,
            "n_permits": [0] * n_flag + [1] * 20,
            "flag_unpermitted": [True] * n_flag + [False] * 20,
        },
        geometry=changed.geometry,
        crs=CRS,
    )
    return pc, parcels


def test_sample_sheet_is_reproducible_and_balanced(cfg: Config) -> None:
    pc, parcels = _sheet_inputs(150, 300)
    s1 = make_sample_sheet(pc, parcels, cfg)
    s2 = make_sample_sheet(pc, parcels, cfg)
    pd.testing.assert_frame_equal(s1, s2)
    assert (s1["group"] == "flagged").sum() == 100
    assert (s1["group"] == "unchanged").sum() == 100
    assert s1["parcel_id"].is_unique
    unch = s1.loc[s1["group"] == "unchanged", "parcel_id"]
    assert not unch.isin(pc["parcel_id"]).any()
    assert {"label", "false_alarm_cause", "note", "lon", "lat"} <= set(s1.columns)
    assert s1["label"].isna().all()


def test_sample_sheet_takes_all_when_few_flags(cfg: Config) -> None:
    pc, parcels = _sheet_inputs(30, 300)
    s = make_sample_sheet(pc, parcels, cfg)
    assert (s["group"] == "flagged").sum() == 30


def test_compute_metrics(cfg: Config) -> None:
    rows = (
        [("flagged", "new", None)] * 70
        + [("flagged", "no_change", "trees")] * 20
        + [("flagged", "no_change", "shadow")] * 10
        + [("unchanged", "no_change", None)] * 92
        + [("unchanged", "expanded", None)] * 8
    )
    sheet = pd.DataFrame(rows, columns=["group", "label", "false_alarm_cause"])
    sheet["parcel_id"] = [f"P{i}" for i in range(len(sheet))]
    m = compute_metrics(sheet, cfg)
    assert (m.tp, m.fp, m.fn, m.tn) == (70, 30, 8, 92)
    assert m.precision == pytest.approx(0.70)
    assert m.miss_rate == pytest.approx(0.08)
    assert m.false_alarm_causes == {"trees": 20, "shadow": 10}
    assert m.n_sample == 200


def test_compute_metrics_rejects_unlabeled_or_bad_labels(cfg: Config) -> None:
    sheet = pd.DataFrame(
        {
            "parcel_id": ["a", "b"],
            "group": ["flagged", "unchanged"],
            "label": ["new", None],
            "false_alarm_cause": [None, None],
        }
    )
    with pytest.raises(ValueError, match="unlabeled"):
        compute_metrics(sheet, cfg)
    sheet["label"] = ["new", "garage"]
    with pytest.raises(ValueError, match="unknown label"):
        compute_metrics(sheet, cfg)


def test_compute_metrics_for_another_models_flags(cfg: Config) -> None:
    sheet = pd.DataFrame(
        {
            "parcel_id": ["a", "b", "c", "d"],
            "group": ["flagged", "flagged", "unchanged", "unchanged"],
            "label": ["new", "no_change", "new", "no_change"],
            "false_alarm_cause": [None, "trees", None, None],
        }
    )
    # Model v1 flags a and c only.
    m = compute_metrics(sheet, cfg, flagged_ids={"a", "c"})
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 0, 0, 2)


def test_choose_labels_prefers_owner(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from parcelwatch.validate import CLAUDE_LABELS, OWNER_LABELS, choose_labels

    sheet = pd.DataFrame(
        {
            "sample_id": ["S001", "S002"],
            "parcel_id": ["a", "b"],
            "group": ["flagged", "unchanged"],
            "label": [None, None],
            "false_alarm_cause": [None, None],
            "note": [None, None],
        }
    )
    with pytest.raises(ValueError):
        choose_labels(sheet, tmp_path)
    pd.DataFrame(
        {
            "sample_id": ["S001", "S002"],
            "label": ["no_change", "no_change"],
            "note": ["[claude]", "[claude]"],
        }
    ).to_csv(tmp_path / CLAUDE_LABELS, index=False)
    out, who = choose_labels(sheet, tmp_path)
    assert who == "claude_provisional" and out["label"].tolist() == ["no_change"] * 2
    # A half-done owner file is ignored; a complete one wins.
    pd.DataFrame({"sample_id": ["S001"], "label": ["new"]}).to_csv(
        tmp_path / OWNER_LABELS, index=False
    )
    assert choose_labels(sheet, tmp_path)[1] == "claude_provisional"
    pd.DataFrame({"sample_id": ["S001", "S002"], "label": ["new", "no_change"]}).to_csv(
        tmp_path / OWNER_LABELS, index=False
    )
    out, who = choose_labels(sheet, tmp_path)
    assert who == "owner" and out["label"].tolist() == ["new", "no_change"]


def test_precision_by_claim() -> None:
    from parcelwatch.validate import precision_by_claim

    sheet = pd.DataFrame({"group": ["flagged"] * 4 + ["unchanged"], "n_new": [1, 1, 0, 0, 0],
                          "n_expanded": [0, 0, 1, 0, 0], "label": ["new", "no_change", "no_change",
                          "no_change", "new"]})  # fmt: skip
    assert precision_by_claim(sheet) == {
        "new": {"n": 2, "confirmed": 1},
        "expanded": {"n": 1, "confirmed": 0},
        "demolished_only": {"n": 1, "confirmed": 0},
    }


def test_claude_labels_accepted_by_owner(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    from parcelwatch.validate import ACCEPTANCE, CLAUDE_LABELS, choose_labels

    sheet = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "parcel_id": ["a"],
            "group": ["flagged"],
            "label": [None],
            "false_alarm_cause": [None],
            "note": [None],
        }
    )
    pd.DataFrame({"sample_id": ["S001"], "label": ["new"]}).to_csv(
        tmp_path / CLAUDE_LABELS, index=False
    )
    assert choose_labels(sheet, tmp_path)[1] == "claude_provisional"
    (tmp_path / ACCEPTANCE).write_text(_json.dumps({"labels": {"accepted_by_owner": True}}))
    assert choose_labels(sheet, tmp_path)[1] == "claude_accepted"
