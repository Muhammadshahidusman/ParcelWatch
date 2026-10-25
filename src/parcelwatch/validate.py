"""F8/F13: validation sample sheet and accuracy metrics (milestone M6)."""

from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd

from parcelwatch.config import Config


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


def make_sample_sheet(
    parcel_changes: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame, cfg: Config
) -> pd.DataFrame:
    """Draw 100 flagged + 100 unchanged parcels (``random_state`` from config) to hand-check.

    Args:
        parcel_changes: Parcel change table with ``flag_unpermitted``.
        parcels: All parcels in the box.
        cfg: Loaded config (``validation`` sample design).

    Returns:
        The blank labeling sheet.
    """
    raise NotImplementedError("M6")


def compute_metrics(sheet: pd.DataFrame, cfg: Config) -> Metrics:
    """Compute precision, miss rate and false-alarm causes from the labeled sheet.

    Args:
        sheet: Hand-labeled validation sheet.
        cfg: Loaded config (labels and causes).

    Returns:
        :class:`Metrics`.
    """
    raise NotImplementedError("M6")


def run(cfg: Config, *, make_sheet: bool, score: bool, force: bool = False) -> None:
    """Make the sample sheet or score the labeled one."""
    raise NotImplementedError("M6")
