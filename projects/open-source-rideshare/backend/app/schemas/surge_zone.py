"""Pydantic schemas for surge pricing zone endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, Field, field_validator


class SurgeZoneCreate(BaseModel):
    """Request body for creating a new surge pricing zone."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None

    # Geographic definition — at least one of polygon or center+radius required
    polygon: list[dict] | None = Field(
        None,
        description=(
            'List of {"lat": ..., "lon": ...} dicts forming the zone boundary. '
            "Must have at least 3 points. Polygon check takes precedence over circle."
        ),
    )
    center_lat: float | None = Field(None, ge=-90.0, le=90.0)
    center_lon: float | None = Field(None, ge=-180.0, le=180.0)
    radius_km: float | None = Field(None, gt=0)

    multiplier: float = Field(1.0, ge=1.0, le=10.0)
    is_active: bool = True

    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = Field(
        None,
        description="Days to apply this zone: 0=Mon, 1=Tue, …, 6=Sun.",
    )

    @field_validator("polygon")
    @classmethod
    def polygon_needs_three_points(cls, v: list[dict] | None) -> list[dict] | None:
        if v is not None and len(v) < 3:
            raise ValueError("polygon must have at least 3 points")
        return v

    @field_validator("days_of_week")
    @classmethod
    def valid_days(cls, v: list[int] | None) -> list[int] | None:
        if v is not None:
            for d in v:
                if d not in range(7):
                    raise ValueError("days_of_week values must be 0-6")
        return v


class SurgeZoneUpdate(BaseModel):
    """Request body for updating an existing surge pricing zone.

    All fields are optional — only supplied fields are changed.
    """

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    polygon: list[dict] | None = None
    center_lat: float | None = Field(None, ge=-90.0, le=90.0)
    center_lon: float | None = Field(None, ge=-180.0, le=180.0)
    radius_km: float | None = Field(None, gt=0)
    multiplier: float | None = Field(None, ge=1.0, le=10.0)
    is_active: bool | None = None
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None


class SurgeZoneResponse(BaseModel):
    """Full surge pricing zone representation returned by admin endpoints."""

    id: uuid.UUID
    name: str
    description: str | None = None
    polygon: list[dict] | None = None
    center_lat: float | None = None
    center_lon: float | None = None
    radius_km: float | None = None
    multiplier: float
    is_active: bool
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SurgeZonePublicResponse(BaseModel):
    """Reduced zone representation for the public /pricing/surge-zones/active endpoint.

    Only exposes information needed for map display — no admin-only metadata.
    """

    id: uuid.UUID
    name: str
    description: str | None = None
    polygon: list[dict] | None = None
    center_lat: float | None = None
    center_lon: float | None = None
    radius_km: float | None = None
    multiplier: float

    model_config = {"from_attributes": True}


class SurgeZoneListResponse(BaseModel):
    zones: list[SurgeZoneResponse]
    total: int


class SurgeZonePublicListResponse(BaseModel):
    zones: list[SurgeZonePublicResponse]
    total: int


class ToggleActiveRequest(BaseModel):
    is_active: bool


# ---------------------------------------------------------------------------
# Surge analytics schemas
# ---------------------------------------------------------------------------


class SurgeSummaryResponse(BaseModel):
    period_days: int
    total_surge_events: int
    zone_surge_events: int
    demand_surge_events: int
    combined_surge_events: int
    avg_combined_multiplier: float
    peak_hour: int | None
    top_zone_name: str | None
    top_zone_event_count: int


class ZoneAnalyticsResponse(BaseModel):
    zone_id: str | None
    zone_name: str
    event_count: int
    avg_multiplier: float
    avg_demand_count: float
    avg_supply_count: float


class ZoneBreakdownResponse(BaseModel):
    period_days: int
    zones: list[ZoneAnalyticsResponse]
    total_zones: int


class DemandHeatmapCellResponse(BaseModel):
    geohash: str
    event_count: int
    avg_combined_multiplier: float


class DemandHeatmapResponse(BaseModel):
    period_days: int
    cells: list[DemandHeatmapCellResponse]
    total_cells: int


class DailyPriceSensitivityResponse(BaseModel):
    date: str
    total_cancellations: int
    price_cancellations: int
    surge_events: int
    price_cancellation_rate: float


class PriceSensitivityResponse(BaseModel):
    period_days: int
    total_cancellations: int
    price_cancellations: int
    price_cancellation_rate: float
    total_surge_events: int
    daily_breakdown: list[DailyPriceSensitivityResponse]
