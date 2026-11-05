"""Generate the exploration notebooks 01_download ... 06_report.

Notebooks only call ``parcelwatch`` functions and display results.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SETUP = """from pathlib import Path
import json
import geopandas as gpd
from parcelwatch.config import load_config
from parcelwatch.paths import Paths

cfg = load_config(Path.cwd().parent / "configs" / "wake_pilot.yaml")
p = Paths(cfg.root)"""

NOTEBOOKS: dict[str, list[tuple[str, str]]] = {
    "01_download": [
        ("md", "# 01 Download\nRaw inputs in `data/raw/`. Run `parcelwatch download` first."),
        ("code", SETUP),
        (
            "code",
            "sorted((f.name, round(f.stat().st_size / 1e6, 1)) for f in p.raw.rglob('*') if f.is_file())",
        ),
    ],
    "02_prepare": [
        (
            "md",
            "# 02 Prepare\nMosaics, clipped vectors, the jurisdiction check and the offset check.",
        ),
        ("code", SETUP),
        (
            "code",
            "import rasterio\nfor f in (p.naip_before, p.naip_after_aligned):\n"
            "    with rasterio.open(f) as s:\n        print(f.name, s.crs, s.res, s.count, s.shape)",
        ),
        ("code", "print(p.jurisdiction_check.read_text())\nprint(p.alignment_report.read_text())"),
        ("code", "from IPython.display import Image\nImage(str(p.offset_dir / 'X1.png'))"),
    ],
    "03_detect": [
        ("md", "# 03 Detect\nBuilding footprints for both years (same model, same settings)."),
        ("code", SETUP),
        (
            "code",
            "for y in ('before', 'after'):\n    g = gpd.read_file(p.buildings(y, 'v0'))\n"
            "    print(y, len(g), round(g.area.median(), 1), 'm2 median')",
        ),
    ],
    "04_changes": [
        ("md", "# 04 Changes\nObject-based change labels, parcel roll-up and permit check."),
        ("code", SETUP),
        ("code", "b = gpd.read_file(p.building_changes_for('v0'))\nb['change'].value_counts()"),
        (
            "code",
            "pc = gpd.read_file(p.parcel_changes_for('v0'))\n"
            "pc[['n_new', 'n_expanded', 'n_demolished', 'n_permits', 'flag_unpermitted']].describe()",
        ),
    ],
    "05_validate": [
        (
            "md",
            "# 05 Validate\nOpen `results/validation_helper.html` to label; then `parcelwatch validate --score`.",
        ),
        ("code", SETUP),
        ("code", "json.loads(p.metrics.read_text()) if p.metrics.exists() else 'not scored yet'"),
    ],
    "06_report": [
        ("md", "# 06 Report\nDollars, public hexes and figures."),
        ("code", SETUP),
        ("code", "json.loads(p.valuation.read_text())"),
        ("code", "json.loads((p.web_data / 'stats.json').read_text())"),
    ],
}


def cell(kind: str, src: str) -> dict:
    """One notebook cell."""
    base = {"cell_type": "markdown" if kind == "md" else "code", "metadata": {},
            "source": src.splitlines(True)}  # fmt: skip
    if kind != "md":
        base.update(execution_count=None, outputs=[])
    return base


if __name__ == "__main__":
    for name, cells in NOTEBOOKS.items():
        nb = {"cells": [cell(k, s) for k, s in cells], "metadata": {"kernelspec": {
              "display_name": "Python 3", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}  # fmt: skip
        out = ROOT / "notebooks" / f"{name}.ipynb"
        out.write_text(json.dumps(nb, indent=1), "utf-8")
        print(out.name)
