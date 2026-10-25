"""F8/F13: validation sample sheet and accuracy metrics (milestone M6)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from parcelwatch.config import Config
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

CHANGE_LABELS = {"new", "expanded", "demolished"}
SHEET_COLUMNS = [
    "sample_id",
    "group",
    "parcel_id",
    "x",
    "y",
    "lon",
    "lat",
    "n_new",
    "n_expanded",
    "n_demolished",
    "added_sqft",
    "n_permits",
    "label",
    "false_alarm_cause",
    "note",
]


@dataclass(frozen=True)
class Metrics:
    """Validation result, written to ``results/metrics.json``."""

    n_sample: int
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    miss_rate: float
    false_alarm_causes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Plain dict for JSON."""
        return asdict(self)


def make_sample_sheet(
    parcel_changes: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame, cfg: Config
) -> pd.DataFrame:
    """Draw 100 flagged + 100 unchanged parcels (``random_state`` from config) to hand-check.

    "Unchanged" means a parcel in the box with no detected change. Rows are shuffled so the
    reviewer can't tell the groups apart by position; the labeling helper hides ``group``.

    Args:
        parcel_changes: Parcel change table with ``flag_unpermitted``.
        parcels: All parcels (rows with ``in_box`` False are ignored).
        cfg: Loaded config (``validation`` sample design).

    Returns:
        The blank labeling sheet with :data:`SHEET_COLUMNS`.
    """
    v = cfg.validation
    seed = v.random_state
    pid = cfg.fields.parcel_id
    in_box = parcels[parcels["in_box"]] if "in_box" in parcels else parcels
    flagged = parcel_changes[parcel_changes["flag_unpermitted"].astype(bool)]
    flagged = flagged.sort_values("parcel_id")
    f_s = flagged.sample(n=min(v.n_flagged, len(flagged)), random_state=seed)
    if len(flagged) < v.n_flagged:
        log.warning("only %d flagged parcels, sampling all of them", len(flagged))
    pool = in_box[~in_box[pid].astype(str).isin(parcel_changes["parcel_id"])].sort_values(pid)
    u_s = pool.sample(n=min(v.n_unchanged, len(pool)), random_state=seed)
    u = gpd.GeoDataFrame(
        {
            "parcel_id": u_s[pid].astype(str).to_numpy(),
            "n_new": 0,
            "n_expanded": 0,
            "n_demolished": 0,
            "added_sqft": 0.0,
            "n_permits": pd.NA,
        },
        geometry=u_s.geometry.to_numpy(),
        crs=parcels.crs,
    )
    cols = [
        "parcel_id",
        "n_new",
        "n_expanded",
        "n_demolished",
        "added_sqft",
        "n_permits",
    ]
    both = pd.concat(
        [f_s[[*cols, "geometry"]].assign(group="flagged"), u.assign(group="unchanged")],
        ignore_index=True,
    )
    both = gpd.GeoDataFrame(both, geometry="geometry", crs=parcels.crs)
    rp = both.representative_point()
    ll = rp.to_crs("EPSG:4326")
    both["x"], both["y"] = rp.x.round(1), rp.y.round(1)
    both["lon"], both["lat"] = ll.x.round(6), ll.y.round(6)
    both = both.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    both["sample_id"] = [f"S{i + 1:03d}" for i in range(len(both))]
    both["label"] = pd.NA
    both["false_alarm_cause"] = pd.NA
    both["note"] = pd.NA
    return pd.DataFrame(both[SHEET_COLUMNS])


def compute_metrics(
    sheet: pd.DataFrame, cfg: Config, flagged_ids: set[str] | None = None
) -> Metrics:
    """Compute precision, miss rate and false-alarm causes from the labeled sheet.

    Labels are ground truth per parcel: ``new``/``expanded``/``demolished`` means a real
    building change is visible, ``no_change`` means none. By default a parcel counts as
    predicted-changed when its ``group`` is ``flagged``. Pass ``flagged_ids`` to score a
    different model's flags on the same sample (the v1 promotion rule).

    Args:
        sheet: Hand-labeled validation sheet.
        cfg: Loaded config (labels and causes).
        flagged_ids: Optional parcel IDs flagged by the model being scored.

    Returns:
        :class:`Metrics`.

    Raises:
        ValueError: If any row is unlabeled or has a label not in the config.
    """
    labels = sheet["label"]
    if labels.isna().any():
        raise ValueError(f"{int(labels.isna().sum())} rows are unlabeled")
    bad = set(labels) - set(cfg.validation.labels)
    if bad:
        raise ValueError(f"unknown label(s) {sorted(bad)}, expected {cfg.validation.labels}")
    truth = labels.isin(CHANGE_LABELS)
    if flagged_ids is None:
        pred = sheet["group"] == "flagged"
    else:
        pred = sheet["parcel_id"].astype(str).isin(flagged_ids)
    tp, fp = int((pred & truth).sum()), int((pred & ~truth).sum())
    fn, tn = int((~pred & truth).sum()), int((~pred & ~truth).sum())
    causes = sheet.loc[pred & ~truth, "false_alarm_cause"].fillna("other").value_counts()
    return Metrics(
        n_sample=len(sheet),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=tp / (tp + fp) if tp + fp else 0.0,
        miss_rate=fn / (fn + tn) if fn + tn else 0.0,
        false_alarm_causes={str(k): int(v) for k, v in causes.items()},
    )


def model_in_use(cfg: Config) -> str:
    """Return the model chosen by the promotion rule (``v0`` until v1 is promoted)."""
    sel = Paths(cfg.root).model_selection
    if sel.exists():
        return str(json.loads(sel.read_text("utf-8"))["model"])
    return "v0"


def run(cfg: Config, *, make_sheet: bool, score: bool, force: bool = False) -> None:
    """Make the sample sheet (and labeling helper) or score the labeled one."""
    from parcelwatch.review import write_labeling_helper

    p = Paths(cfg.root)
    model = model_in_use(cfg)
    if make_sheet:
        if p.validation_sheet.exists() and not force:
            log.info("validation sheet exists, not overwriting labels (use --force)")
        else:
            pc = gpd.read_file(p.parcel_changes_for(model))
            parcels = gpd.read_file(p.parcels_clipped)
            sheet = make_sample_sheet(pc, parcels, cfg)
            sheet.to_csv(p.validation_sheet, index=False)
            log.info("validation sheet: %d rows -> %s", len(sheet), p.validation_sheet)
        write_labeling_helper(cfg, pd.read_csv(p.validation_sheet, dtype={"parcel_id": str}))
    if score:
        sheet = pd.read_csv(p.validation_sheet, dtype={"parcel_id": str})
        sheet, who = choose_labels(sheet, p.results)
        log.info("scoring with labels from: %s", who)
        result: dict[str, dict[str, Any]] = {}
        for m in ("v0", "v1"):
            path = p.parcel_changes_for(m)
            if not path.exists():
                continue
            pc = gpd.read_file(path)
            ids = set(pc.loc[pc["flag_unpermitted"].astype(bool), "parcel_id"].astype(str))
            result[m] = compute_metrics(sheet, cfg, None if m == "v0" else ids).to_dict()
        chosen = "v0"
        if "v1" in result:
            v0p, v1p = result["v0"]["precision"], result["v1"]["precision"]
            chosen = "v1" if v1p >= v0p else "v0"
        metrics = {
            **result[chosen],
            "model": chosen,
            "by_model": result,
            "labeled_by": who,
        }
        p.metrics.write_text(json.dumps(metrics, indent=2), "utf-8")
        p.model_selection.write_text(
            json.dumps({"model": chosen, "rule": cfg.model.promote_v1_if}, indent=2),
            "utf-8",
        )
        log.info(
            "metrics (%s): precision %.2f, miss rate %.2f",
            chosen,
            metrics["precision"],
            metrics["miss_rate"],
        )


OWNER_LABELS = "validation_labels.csv"  # exported by the HTML helper
CLAUDE_LABELS = "validation_labels_claude.csv"  # provisional, replaced by the owner's


def _complete(labels: pd.DataFrame, n: int) -> bool:
    return len(labels) >= n and labels["label"].notna().all()


def apply_labels(sheet: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Replace the sheet's label, cause and note columns with ``labels`` by ``sample_id``."""
    lab = labels.set_index("sample_id")
    out = sheet.set_index("sample_id")
    for col in ("label", "false_alarm_cause", "note"):
        out[col] = lab[col].reindex(out.index) if col in lab else pd.NA
    return out.reset_index()


def choose_labels(sheet: pd.DataFrame, results: Path) -> tuple[pd.DataFrame, str]:
    """Pick the label source: owner helper export, then labels typed into the sheet,
    then Claude's provisional labels. The owner's labels always win.

    Returns:
        ``(labeled_sheet, source)`` with source ``owner`` or ``claude_provisional``.

    Raises:
        ValueError: If no complete set of labels exists.
    """
    n = len(sheet)
    owner = results / OWNER_LABELS
    if owner.exists():
        lab = pd.read_csv(owner)
        if _complete(lab, n):
            return apply_labels(sheet, lab), "owner"
        log.warning(
            "%s has %d of %d labels, not used yet", owner.name, int(lab["label"].notna().sum()), n
        )
    if _complete(sheet, n):
        return sheet, "owner"
    claude = results / CLAUDE_LABELS
    if claude.exists():
        lab = pd.read_csv(claude)
        if _complete(lab, n):
            return apply_labels(sheet, lab), "claude_provisional"
    raise ValueError("no complete set of validation labels yet")
