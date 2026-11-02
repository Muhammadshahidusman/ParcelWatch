"""Pydantic v2 models for ``configs/wake_pilot.yaml``.

The YAML file is the single source of truth for every parameter, URL, date and field
name. Code reads values from a loaded :class:`Config`, never from literals.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BBox = tuple[float, float, float, float]


class _Strict(BaseModel):
    """Base model that rejects unknown keys so config typos fail loudly."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_bbox(v: BBox) -> BBox:
    """Ensure a bbox is ordered (min_x, min_y, max_x, max_y)."""
    min_x, min_y, max_x, max_y = v
    if not (min_x < max_x and min_y < max_y):
        raise ValueError(f"bbox must be (min_x, min_y, max_x, max_y), got {v}")
    return v


class ProjectConfig(_Strict):
    """Project identity."""

    name: str
    version: str


class AOIConfig(_Strict):
    """Study area box and coordinate systems."""

    county: str
    name: str
    bbox_wgs84: BBox
    bbox_utm17n: BBox
    area_km2: float = Field(gt=0)
    jurisdiction_share_pct: dict[str, float]
    working_crs: str
    web_crs: str

    _bbox_wgs84 = field_validator("bbox_wgs84")(_check_bbox)
    _bbox_utm = field_validator("bbox_utm17n")(_check_bbox)

    @model_validator(mode="after")
    def _area_matches_box(self) -> AOIConfig:
        """Check the stated area matches the UTM box to within 1%."""
        min_x, min_y, max_x, max_y = self.bbox_utm17n
        box_km2 = (max_x - min_x) * (max_y - min_y) / 1e6
        if abs(box_km2 - self.area_km2) / self.area_km2 > 0.01:
            raise ValueError(f"area_km2={self.area_km2} but bbox_utm17n is {box_km2:.2f} km2")
        return self


class ImageryDate(_Strict):
    """One NAIP acquisition: year, flight date and exact STAC item IDs."""

    year: int
    date: date
    items: list[str] = Field(min_length=1)


class ImageryConfig(_Strict):
    """NAIP source on Microsoft Planetary Computer."""

    source: Literal["planetary_computer"]
    stac_url: str
    collection: str
    gsd_m: float = Field(gt=0)
    bands: list[str]
    before: ImageryDate
    after: ImageryDate

    @model_validator(mode="after")
    def _before_precedes_after(self) -> ImageryConfig:
        """The Before image must be flown before the After image."""
        if self.before.date >= self.after.date:
            raise ValueError("imagery.before.date must be earlier than imagery.after.date")
        return self


class VectorsConfig(_Strict):
    """ArcGIS Hub download URLs and source CRSs for vector inputs."""

    parcels_download: str
    parcels_source_crs: str
    permits_download: str
    permits_xy_crs: str
    corporate_limits_download: str
    overture_type: str
    refresh: str

    @field_validator("parcels_download", "permits_download", "corporate_limits_download")
    @classmethod
    def _never_wake_server(cls, v: str) -> str:
        """Wake's own server blocks the owner's network; only Hub URLs are allowed."""
        if "maps.wake.gov" in v or "maps.wakegov.com" in v:
            raise ValueError(f"never call Wake's own server, use ArcGIS Hub: {v}")
        return v


class FieldsConfig(_Strict):
    """Verified source field names for parcels and permits."""

    parcel_id: str
    real_estate_id: str
    building_value: str
    land_value: str
    total_value: str
    heated_area_sqft: str
    year_built: str
    city: str
    planning_jurisdiction: str
    land_class: str
    never_load: list[str]
    permit_id: str
    permit_parcel_id: str
    permit_issue_date: str
    permit_type: str
    permit_work_class: str
    permit_square_feet: str
    permit_valuation: str
    permit_district: str
    permit_x: str
    permit_y: str


class PermitsConfig(_Strict):
    """Permit window, counting types and match rule."""

    window_start: date
    window_end: date
    counting_types: list[str] = Field(min_length=1)
    match_by: list[Literal["spatial", "pin"]] = Field(min_length=1)

    @model_validator(mode="after")
    def _window_ordered(self) -> PermitsConfig:
        """Window start must precede window end."""
        if self.window_start >= self.window_end:
            raise ValueError("permits.window_start must be earlier than permits.window_end")
        return self


class ModelV0Config(_Strict):
    """Pretrained GeoAI building footprint extractor (baseline)."""

    type: str
    weights: str
    input_bands: list[str]
    confidence_threshold: float = Field(ge=0, le=1)
    mask_threshold: float = Field(ge=0, le=1)
    orthogonalize_epsilon: float = Field(ge=0)


class ModelV1Config(_Strict):
    """Fine-tuned 4-channel Mask R-CNN."""

    type: str
    num_channels: int = Field(gt=0)
    tile_size: int = Field(gt=0)
    stride: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    epochs: int = Field(gt=0)
    learning_rate: float = Field(gt=0)
    val_split: float = Field(gt=0, lt=1)
    confidence_threshold: float = Field(ge=0, le=1)
    window_size: int = Field(gt=0)
    overlap: int = Field(ge=0)
    label_spot_check: int = Field(ge=0)


class ModelConfig(_Strict):
    """Both detection models and the promotion rule."""

    v0: ModelV0Config
    v1: ModelV1Config
    promote_v1_if: str
    seed: int


class ChangeConfig(_Strict):
    """Object-based change classification thresholds."""

    match_tolerance_m: float = Field(gt=0)
    tolerance_rule: str
    offset_check_points: int = Field(gt=0)
    min_building_area_m2: float = Field(ge=0)
    expanded_min_added_m2: float = Field(ge=0)
    expanded_min_ratio: float = Field(ge=1)
    flag_change_types: list[Literal["new", "expanded", "demolished"]] = Field(min_length=1)


class ValidationTargets(_Strict):
    """Accuracy targets from the PRD."""

    precision_min: float = Field(ge=0, le=1)
    miss_rate_max: float = Field(ge=0, le=1)


class ValidationConfig(_Strict):
    """Hand-check sample design."""

    n_flagged: int = Field(gt=0)
    n_unchanged: int = Field(gt=0)
    random_state: int
    labels: list[str]
    false_alarm_causes: list[str]
    targets: ValidationTargets


class ValueFilters(_Strict):
    """Filters for the value-per-sq-ft sample."""

    min_heated_sqft: float
    min_building_value: float


class ValuationConfig(_Strict):
    """Tax rates and the value-per-sq-ft method."""

    tax_year: int
    assessment_ratio: float = Field(gt=0)
    county_rate_cents_per_100: float = Field(ge=0)
    municipal_rate_cents_per_100: dict[str, float]
    include_fire_tax: bool
    value_per_sqft_method: str
    recent_build_years: int = Field(gt=0)
    value_per_sqft_filters: ValueFilters
    value_per_sqft_scope: str
    value_per_sqft_min_sample: int = Field(gt=0)
    sqft_per_m2: float = Field(gt=0)

    @field_validator("municipal_rate_cents_per_100")
    @classmethod
    def _has_default(cls, v: dict[str, float]) -> dict[str, float]:
        """A ``default`` rate (unincorporated) must be present."""
        if "default" not in v:
            raise ValueError("municipal_rate_cents_per_100 needs a 'default' entry")
        return v

    def municipal_rate(self, city: str | None) -> float:
        """Return the town rate in cents per $100 for a parcel's ``CITY_DECODE``."""
        key = (city or "").strip().upper()
        return self.municipal_rate_cents_per_100.get(
            key, self.municipal_rate_cents_per_100["default"]
        )


class PrivacyConfig(_Strict):
    """Public aggregation rule."""

    public_aggregation: Literal["h3"]
    h3_resolution: int = Field(ge=0, le=15)
    min_parcels_per_hex: int = Field(gt=0)


class OutputConfig(_Strict):
    """Output file formats."""

    vector_format: str
    web_tiles: str


class Config(_Strict):
    """The whole validated pipeline configuration."""

    project: ProjectConfig
    aoi: AOIConfig
    imagery: ImageryConfig
    vectors: VectorsConfig
    fields: FieldsConfig
    permits: PermitsConfig
    model: ModelConfig
    change: ChangeConfig
    validation: ValidationConfig
    valuation: ValuationConfig
    privacy: PrivacyConfig
    output: OutputConfig

    # Not part of the YAML: set by load_config for traceability.
    source_path: Path | None = Field(default=None, exclude=True)
    sha256: str | None = Field(default=None, exclude=True)

    @property
    def root(self) -> Path:
        """Project root, taken as the parent of the ``configs/`` folder."""
        if self.source_path is None:
            return Path.cwd()
        return self.source_path.resolve().parent.parent


def load_config(path: str | Path) -> Config:
    """Load and validate a pipeline YAML config.

    Args:
        path: Path to a YAML file such as ``configs/wake_pilot.yaml``.

    Returns:
        A frozen, validated :class:`Config` carrying the file's path and SHA-256 hash.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        pydantic.ValidationError: If any value is missing, mistyped or out of range.
    """
    p = Path(path)
    raw_bytes = p.read_bytes()
    data = yaml.safe_load(raw_bytes)
    cfg = Config.model_validate(data)
    return cfg.model_copy(
        update={"source_path": p, "sha256": hashlib.sha256(raw_bytes).hexdigest()}
    )
