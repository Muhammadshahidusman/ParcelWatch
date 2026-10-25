"""Generate notebooks/colab_train_v1.ipynb (kept as code so the notebook never drifts)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def md(s: str) -> dict:
    """Markdown cell."""
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": s.strip("\n").splitlines(True),
    }


def code(s: str) -> dict:
    """Code cell."""
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": s.strip("\n").splitlines(True),
    }


CELLS = [
    md("""
# ParcelWatch v1: fine-tune the 4-band Mask R-CNN on Colab

Runtime > Change runtime type > **T4 GPU**. Then run every cell top to bottom (about 2 to 3 hours).

Before you start, upload two files to the Google Drive folder `MyDrive/parcelwatch/`:

1. `dist/parcelwatch_src.zip`
2. `dist/v1_tiles.zip`

Both are made on the laptop by `python scripts/pack_for_colab.py`.

When it finishes, download `MyDrive/parcelwatch/models/v1/best_model.pth` and
`train_settings.json` into `D:/ParcelWatch/models/v1/`. All settings come from
`configs/wake_pilot.yaml` (50 epochs, batch 4, learning rate 0.005, seed 42).
"""),
    code("""
from google.colab import drive
drive.mount('/content/drive')
DRIVE = '/content/drive/MyDrive/parcelwatch'
"""),
    code("""
!nvidia-smi --query-gpu=name,memory.total --format=csv
!mkdir -p /content/pw/data/training && cd /content/pw && unzip -q -o $DRIVE/parcelwatch_src.zip && unzip -q -o $DRIVE/v1_tiles.zip -d data/training/
!cd /content/pw && pip -q install -e ".[ml]"
"""),
    code("""
import sys, pathlib
sys.path.insert(0, '/content/pw/src')
from parcelwatch.config import load_config
from parcelwatch.detect import train_v1

cfg = load_config('/content/pw/configs/wake_pilot.yaml')
tiles = pathlib.Path('/content/pw/data/training/v1_tiles')
print(len(list((tiles / 'images').glob('*.tif'))), 'training tiles')
print(cfg.model.v1)
"""),
    code("""
# Checkpoints go straight to Drive, so a disconnect loses nothing.
out = pathlib.Path(DRIVE) / 'models' / 'v1'
best = train_v1(tiles, out, cfg)
print('best weights:', best)
"""),
    md("""
Done. Download `MyDrive/parcelwatch/models/v1/best_model.pth` and `train_settings.json` to
`D:/ParcelWatch/models/v1/`, then tell Claude: "Colab training finished, best_model.pth is in models/v1."
"""),
]


if __name__ == "__main__":
    nb = {
        "cells": CELLS,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = ROOT / "notebooks" / "colab_train_v1.ipynb"
    out.write_text(json.dumps(nb, indent=1), "utf-8")
    print(out)
