"""F3/F4: building detection with the v0 pretrained extractor and the v1 Mask R-CNN (M3, M5)."""

from __future__ import annotations

from pathlib import Path

from parcelwatch.config import Config


def run_v0(image: Path, out: Path, cfg: Config) -> Path:
    """Detect buildings with GeoAI ``BuildingFootprintExtractor`` (RGB, pretrained).

    Args:
        image: Processed NAIP mosaic for one year.
        out: Output GeoPackage of building polygons.
        cfg: Loaded config (``model.v0`` settings, identical for both years).

    Returns:
        ``out``.
    """
    raise NotImplementedError("M3")


def make_training_tiles(image: Path, labels: Path, out_dir: Path, cfg: Config) -> Path:
    """Cut 4-band image tiles and Overture label masks for v1 training.

    Args:
        image: After mosaic.
        labels: Overture buildings clipped to the box.
        out_dir: Folder under ``data/training/``.
        cfg: Loaded config (``model.v1`` tile size and stride).

    Returns:
        ``out_dir``.
    """
    raise NotImplementedError("M5")


def train_v1(tiles_dir: Path, out_dir: Path, cfg: Config) -> Path:
    """Fine-tune the 4-channel Mask R-CNN (runs on Colab).

    Args:
        tiles_dir: Training tiles from :func:`make_training_tiles`.
        out_dir: Folder for checkpoints.
        cfg: Loaded config (``model.v1`` and seed).

    Returns:
        Path to the best weights file.
    """
    raise NotImplementedError("M5")


def run_v1(image: Path, model: Path, out: Path, cfg: Config) -> Path:
    """Detect buildings with the fine-tuned v1 model.

    Args:
        image: Processed NAIP mosaic for one year.
        model: v1 weights under ``models/``.
        out: Output GeoPackage of building polygons.
        cfg: Loaded config (``model.v1`` inference settings).

    Returns:
        ``out``.
    """
    raise NotImplementedError("M5")


def run(cfg: Config, model: str, *, train: bool = False, force: bool = False) -> None:
    """Run detection for both years with the chosen model."""
    raise NotImplementedError("M3")
