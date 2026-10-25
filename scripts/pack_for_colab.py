"""Zip the code and the v1 training tiles for upload to Google Drive (Colab training)."""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pack_source(out: Path) -> None:
    """Zip pyproject, configs and src/ (no data, no secrets)."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in ["pyproject.toml", "README.md", "LICENSE"]:
            zf.write(ROOT / rel, rel)
        for folder in ["configs", "src"]:
            for f in (ROOT / folder).rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    zf.write(f, f.relative_to(ROOT).as_posix())


def pack_tiles(out: Path) -> None:
    """Zip data/training/v1_tiles/{images,labels}."""
    tiles = ROOT / "data" / "training"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
        for sub in ["v1_tiles/images", "v1_tiles/labels"]:
            for f in (tiles / sub).glob("*.tif"):
                zf.write(f, f.relative_to(tiles).as_posix())


if __name__ == "__main__":
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    pack_source(dist / "parcelwatch_src.zip")
    pack_tiles(dist / "v1_tiles.zip")
    print("Upload these to MyDrive/parcelwatch/:", *sorted(dist.glob("*.zip")), sep="\n  ")
