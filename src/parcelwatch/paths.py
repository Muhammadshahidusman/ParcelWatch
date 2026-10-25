"""Standard file locations, all relative to the project root (CLAUDE.md section 4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Every input and output path the pipeline reads or writes."""

    root: Path

    @property
    def raw(self) -> Path:
        """Downloads, never modified."""
        return self.root / "data" / "raw"

    @property
    def processed(self) -> Path:
        """Mosaicked, aligned and clipped layers."""
        return self.root / "data" / "processed"

    @property
    def training(self) -> Path:
        """Image and label tiles for v1."""
        return self.root / "data" / "training"

    @property
    def models(self) -> Path:
        """Model weights (gitignored)."""
        return self.root / "models"

    @property
    def results(self) -> Path:
        """Change tables, validation sheet, figures."""
        return self.root / "results"

    @property
    def logs(self) -> Path:
        """Per-command run logs."""
        return self.results / "logs"

    @property
    def web_data(self) -> Path:
        """Public outputs only: H3 PMTiles and stats.json."""
        return self.root / "web" / "data"

    # Raw inputs
    def naip_raw(self, which: str) -> Path:
        """Folder of raw NAIP tiles for ``before`` or ``after``."""
        return self.raw / f"naip_{which}"

    @property
    def parcels_zip(self) -> Path:
        """Full-county parcel shapefile zip from ArcGIS Hub."""
        return self.raw / "wake_parcels.zip"

    @property
    def permits_csv(self) -> Path:
        """Full-county permit CSV from ArcGIS Hub."""
        return self.raw / "wake_permits.csv"

    @property
    def corporate_limits(self) -> Path:
        """Town limits GeoJSON from ArcGIS Hub."""
        return self.raw / "wake_corporate_limits.geojson"

    @property
    def overture_buildings(self) -> Path:
        """Cached Overture building footprints for the box."""
        return self.raw / "overture_buildings.parquet"

    # Processed and results
    @property
    def naip_before(self) -> Path:
        """Before mosaic in EPSG:26917."""
        return self.processed / "naip_before.tif"

    @property
    def naip_after_aligned(self) -> Path:
        """After mosaic resampled onto the Before grid."""
        return self.processed / "naip_after_aligned.tif"

    @property
    def alignment_report(self) -> Path:
        """Measured offset and the derived match tolerance."""
        return self.results / "alignment_report.json"

    def buildings(self, year_key: str, model: str) -> Path:
        """Detected building footprints for ``before``/``after`` and ``v0``/``v1``."""
        return self.results / f"buildings_{year_key}_{model}.gpkg"

    @property
    def building_changes(self) -> Path:
        """Labeled building changes (private)."""
        return self.results / "building_changes.gpkg"

    @property
    def parcel_changes(self) -> Path:
        """Parcel-level change table (private, never published)."""
        return self.results / "parcel_changes.gpkg"

    @property
    def validation_sheet(self) -> Path:
        """Hand-labeling sheet (private)."""
        return self.results / "validation_sheet.csv"

    @property
    def metrics(self) -> Path:
        """Validation metrics."""
        return self.results / "metrics.json"

    @property
    def valuation(self) -> Path:
        """Value per sq ft and tax totals."""
        return self.results / "valuation.json"

    @property
    def run_manifest(self) -> Path:
        """Config hash, git commit, item IDs, model and timestamps."""
        return self.results / "run_manifest.json"
