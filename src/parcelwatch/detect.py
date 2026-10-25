"""F3/F4: building detection with the v0 pretrained extractor and the v1 Mask R-CNN (M3, M5).

Rule 3: same model, same settings, both dates. Both years go through :func:`_detect_year`
with identical arguments.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import geopandas as gpd

from parcelwatch.config import Config
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

YEARS = ("before", "after")


def _image_for(p: Paths, year_key: str) -> Path:
    return p.naip_before if year_key == "before" else p.naip_after_aligned


def _min_object_px(cfg: Config) -> int:
    """The config's minimum building area expressed in pixels (geoai counts pixels)."""
    return max(1, int(cfg.change.min_building_area_m2 / cfg.imagery.gsd_m**2))


def _masks_to_buildings(mask: Path, out: Path, cfg: Config, model: str) -> Path:
    """Vectorize and orthogonalize a building mask GeoTIFF into a GeoPackage."""
    import geoai

    geojson = out.with_suffix(".geojson")
    gdf = geoai.orthogonalize(str(mask), str(geojson), epsilon=cfg.model.v0.orthogonalize_epsilon)
    if gdf is None or len(gdf) == 0:
        gdf = gpd.GeoDataFrame(geometry=[], crs=cfg.aoi.working_crs)
    gdf = gdf.to_crs(cfg.aoi.working_crs) if gdf.crs else gdf.set_crs(cfg.aoi.working_crs)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf["geometry"] = gdf.geometry.make_valid()
    gdf = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gpd.GeoDataFrame(
        {"model": model, "area_m2": gdf.geometry.area},
        geometry=gdf.geometry,
        crs=cfg.aoi.working_crs,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, layer="buildings", driver="GPKG")
    geojson.unlink(missing_ok=True)
    log.info("%s: %d building polygons", out.name, len(gdf))
    return out


def run_v0(image: Path, out: Path, cfg: Config, extractor: Any = None) -> Path:
    """Detect buildings with GeoAI ``BuildingFootprintExtractor`` (RGB, pretrained).

    Writes a building mask with the config thresholds, then orthogonalizes it.

    Args:
        image: Processed NAIP mosaic for one year (bands R, G, B, NIR; the first 3 are used).
        out: Output GeoPackage of building polygons.
        cfg: Loaded config (``model.v0`` settings, identical for both years).
        extractor: Optional pre-loaded extractor to reuse between years.

    Returns:
        ``out``.
    """
    import geoai

    v0 = cfg.model.v0
    ext = extractor or geoai.BuildingFootprintExtractor(model_path=v0.weights)
    mask = out.with_name(out.stem + "_mask.tif")
    ext.save_masks_as_geotiff(
        str(image),
        output_path=str(mask),
        confidence_threshold=v0.confidence_threshold,
        mask_threshold=v0.mask_threshold,
        min_object_area=_min_object_px(cfg),
        verbose=True,
    )
    return _masks_to_buildings(mask, out, cfg, "v0")


def make_training_tiles(image: Path, labels: Path, out_dir: Path, cfg: Config) -> Path:
    """Cut 4-band image tiles and Overture label masks for v1 training.

    Args:
        image: After mosaic (4 bands).
        labels: Overture buildings clipped to the box.
        out_dir: Folder under ``data/training/`` (gets ``images/`` and ``labels/``).
        cfg: Loaded config (``model.v1`` tile size and stride).

    Returns:
        ``out_dir``.
    """
    import geoai

    v1 = cfg.model.v1
    lab = gpd.read_file(labels)
    lab = lab[["geometry"]].assign(**{"class": 1})
    lab_path = out_dir / "labels.geojson"
    out_dir.mkdir(parents=True, exist_ok=True)
    lab.to_crs(cfg.aoi.working_crs).to_file(lab_path, driver="GeoJSON")
    geoai.export_geotiff_tiles(
        in_raster=str(image),
        out_folder=str(out_dir),
        in_class_data=str(lab_path),
        tile_size=v1.tile_size,
        stride=v1.stride,
        class_value_field="class",
        buffer_radius=0,
        quiet=True,
    )
    dropped = drop_unlabeled_tiles(out_dir, unlabeled_parcels(cfg))
    n = len(list((out_dir / "images").glob("*.tif")))
    log.info(
        "training tiles: %d kept, %d dropped for missing labels (%d px, stride %d)",
        n,
        dropped,
        v1.tile_size,
        v1.stride,
    )
    return out_dir


def unlabeled_parcels(cfg: Config) -> gpd.GeoDataFrame:
    """Box parcels with a house built by the After year but no Overture footprint.

    Overture misses many 2021-22 builds; tiles over these parcels would teach the model
    that new houses are background, so they are left out of training.
    """
    p = Paths(cfg.root)
    f = cfg.fields
    parcels = gpd.read_file(p.parcels_clipped)
    parcels = parcels[parcels["in_box"]]
    built = parcels[
        (parcels[f.heated_area_sqft] > 0) & (parcels[f.year_built] <= cfg.imagery.after.year)
    ]
    ov = gpd.read_file(p.overture_clipped)
    pts = gpd.GeoDataFrame(geometry=ov.representative_point(), crs=ov.crs)
    hit = gpd.sjoin(pts, built[[f.parcel_id, "geometry"]], predicate="within")[f.parcel_id]
    return built[~built[f.parcel_id].isin(hit)]


def drop_unlabeled_tiles(tiles_dir: Path, unlabeled: gpd.GeoDataFrame) -> int:
    """Delete image/label tile pairs that overlap any unlabeled parcel; return the count."""
    import rasterio
    from shapely.geometry import box

    sindex = unlabeled.sindex
    dropped = 0
    for img in sorted((tiles_dir / "images").glob("*.tif")):
        with rasterio.open(img) as src:
            tile = box(*src.bounds)
        if len(sindex.query(tile, predicate="intersects")):
            img.unlink()
            (tiles_dir / "labels" / img.name).unlink(missing_ok=True)
            dropped += 1
    return dropped


def train_v1(tiles_dir: Path, out_dir: Path, cfg: Config, batch_size: int | None = None) -> Path:
    """Fine-tune the 4-channel Mask R-CNN on the training tiles.

    Args:
        tiles_dir: Training tiles from :func:`make_training_tiles`.
        out_dir: Folder for checkpoints (``models/v1``).
        cfg: Loaded config (``model.v1`` and seed).
        batch_size: Override only when GPU memory forces it (logged in the run manifest).

    Returns:
        Path to the best weights file.
    """
    import geoai

    v1 = cfg.model.v1
    bs = batch_size or v1.batch_size
    out_dir.mkdir(parents=True, exist_ok=True)
    geoai.train_MaskRCNN_model(
        images_dir=str(tiles_dir / "images"),
        labels_dir=str(tiles_dir / "labels"),
        output_dir=str(out_dir),
        num_channels=v1.num_channels,
        pretrained=True,
        batch_size=bs,
        num_epochs=v1.epochs,
        learning_rate=v1.learning_rate,
        seed=cfg.model.seed,
        val_split=v1.val_split,
        verbose=True,
    )
    best = out_dir / "best_model.pth"
    (out_dir / "train_settings.json").write_text(
        json.dumps({**v1.model_dump(), "batch_size_used": bs, "seed": cfg.model.seed}, indent=2)
    )
    return best


def run_v1(image: Path, model: Path, out: Path, cfg: Config) -> Path:
    """Detect buildings with the fine-tuned v1 model.

    Args:
        image: Processed NAIP mosaic for one year (4 bands).
        model: v1 weights under ``models/``.
        out: Output GeoPackage of building polygons.
        cfg: Loaded config (``model.v1`` inference settings).

    Returns:
        ``out``.
    """
    import geoai

    v1 = cfg.model.v1
    mask = out.with_name(out.stem + "_mask.tif")
    geoai.object_detection(
        str(image),
        str(mask),
        str(model),
        window_size=v1.window_size,
        overlap=v1.overlap,
        confidence_threshold=v1.confidence_threshold,
        batch_size=v1.batch_size,
        num_channels=v1.num_channels,
    )
    return _masks_to_buildings(mask, out, cfg, "v1")


def run(cfg: Config, model: str, *, train: bool = False, force: bool = False) -> None:
    """Run detection for both years with the chosen model and identical settings."""
    p = Paths(cfg.root)
    if train:
        tiles = p.training / "v1_tiles"
        if force or not (tiles / "images").exists():
            make_training_tiles(p.naip_after_aligned, p.overture_clipped, tiles, cfg)
    if model == "v0":
        import geoai

        extractor = None
        for year in YEARS:
            out = p.buildings(year, "v0")
            if out.exists() and not force:
                log.info("%s exists, skipping", out.name)
                continue
            extractor = extractor or geoai.BuildingFootprintExtractor(
                model_path=cfg.model.v0.weights
            )
            run_v0(_image_for(p, year), out, cfg, extractor)
    elif model == "v1":
        weights = p.models / "v1" / "best_model.pth"
        if not weights.exists():
            raise FileNotFoundError(
                f"{weights} missing: train v1 first (notebooks/colab_train_v1.ipynb)"
            )
        for year in YEARS:
            out = p.buildings(year, "v1")
            if out.exists() and not force:
                log.info("%s exists, skipping", out.name)
                continue
            run_v1(_image_for(p, year), weights, out, cfg)
    else:
        raise ValueError(f"unknown model {model!r}")
