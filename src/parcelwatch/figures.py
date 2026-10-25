"""Static figures per DESIGN section 10 (README, case study, slides)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np

from parcelwatch.config import Config
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

CAPTION = "Imagery: USDA NAIP. Data: Wake County, NC; Overture Maps Foundation."
STYLE = Path(__file__).with_name("parcelwatch.mplstyle")
INK, MUTED, BORDER = "#0F172A", "#5B6676", "#E3E6EA"
HALF_M = 200.0  # before/after crops are 400 x 400 m


def _crop(raster: Path, cx: float, cy: float, half: float) -> np.ndarray:
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(raster) as src:
        win = from_bounds(cx - half, cy - half, cx + half, cy + half, transform=src.transform)
        arr = src.read([1, 2, 3], window=win, boundless=True)
    return np.moveaxis(arr, 0, -1)


def _pill(ax: Any, text: str) -> None:
    ax.text(
        0.03,
        0.96,
        text,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=12,
        fontweight="semibold",
        color=INK,
        bbox={
            "boxstyle": "round,pad=0.35,rounding_size=0.8",
            "fc": "white",
            "ec": BORDER,
        },
    )


def _scale_bar(ax: Any, half: float) -> None:
    x1, y0 = half * 0.92, -half * 0.9
    ax.plot([x1 - 100, x1], [y0, y0], color="white", lw=4, solid_capstyle="butt")
    ax.plot([x1 - 100, x1], [y0, y0], color=INK, lw=2, solid_capstyle="butt")
    ax.text(
        x1 - 50,
        y0 + half * 0.03,
        "100 m",
        ha="center",
        va="bottom",
        fontsize=10,
        color="white",
        fontweight="semibold",
    )


def before_after(
    cfg: Config, center: tuple[float, float], out: Path, size_px: tuple[int, int]
) -> Path:
    """Draw a Before/After pair with identical extent and scale around ``center``."""
    import matplotlib.pyplot as plt

    p = Paths(cfg.root)
    w, h = size_px
    with plt.style.context(str(STYLE)):
        fig, axes = plt.subplots(1, 2, figsize=(w / 150, h / 150), dpi=150)
        for ax, path, year in (
            (axes[0], p.naip_before, cfg.imagery.before.year),
            (axes[1], p.naip_after_aligned, cfg.imagery.after.year),
        ):
            ax.imshow(_crop(path, *center, HALF_M), extent=(-HALF_M, HALF_M, -HALF_M, HALF_M))
            ax.set_axis_off()
            _pill(ax, str(year))
            _scale_bar(ax, HALF_M)
        fig.text(0.01, 0.015, CAPTION, fontsize=9, color=MUTED)
        fig.subplots_adjust(left=0.01, right=0.99, top=0.98, bottom=0.07, wspace=0.02)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=150)
        plt.close(fig)
    return out


def false_alarm_chart(causes: dict[str, int], out: Path) -> Path:
    """Horizontal bar chart of false-alarm causes, sorted descending, labeled bars, no legend."""
    import matplotlib.pyplot as plt

    items = sorted(causes.items(), key=lambda kv: kv[1])
    with plt.style.context(str(STYLE)):
        fig, ax = plt.subplots(figsize=(8, 5.33), dpi=150)
        labels = [k.replace("_", " ") for k, _ in items]
        vals = [v for _, v in items]
        bars = ax.barh(labels, vals, color="#5B6676")
        ax.bar_label(bars, padding=4, fontsize=11, color=INK)
        ax.set_xlabel("False alarms in the hand-checked sample")
        ax.grid(axis="y", visible=False)
        fig.text(0.01, 0.01, CAPTION, fontsize=8, color=MUTED)
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(out)
        plt.close(fig)
    return out


def make_figures(cfg: Config, hexes: gpd.GeoDataFrame, stats: dict[str, Any]) -> list[Path]:
    """Make every static figure and copy the public ones to ``web/img/``.

    The example neighborhood is the hex with the most flags, shown as imagery only
    (no parcel lines or IDs).
    """
    p = Paths(cfg.root)
    figs = p.results / "figures"
    web_img = cfg.root / "web" / "img"
    web_img.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    if not hexes.empty:
        top = hexes.sort_values(["n_flagged", "n_changed"], ascending=False).iloc[0]
        c = gpd.GeoSeries([top.geometry.centroid], crs="EPSG:4326").to_crs(cfg.aoi.working_crs)[0]
        for name, size in (
            ("before_after_slide", (1600, 900)),
            ("before_after_readme", (1200, 800)),
        ):
            made.append(before_after(cfg, (c.x, c.y), figs / f"{name}.png", size))
    if stats.get("false_alarm_causes"):
        made.append(false_alarm_chart(stats["false_alarm_causes"], figs / "false_alarm_causes.png"))
    for f in made:
        shutil.copyfile(f, web_img / f.name)
    log.info("figures: %s", [f.name for f in made])
    return made
