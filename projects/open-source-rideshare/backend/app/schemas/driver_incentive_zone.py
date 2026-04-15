"""Pydantic schemas for Driver Incentive Zone endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.driver_incentive_zone import IncentiveBonusType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateIncentiveZoneRequest(BaseModel):
    """Admin request body to create a new incentive zone."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation of why this zone exists (cooperative transparency).",
    )

    # Geographic definition — polygon OR circle required.
    polygon: list[dict[str, Any]] | None = Field(
        None,
        description="List of {lat, lon} dicts forming the zone boundary polygon.",
    )
    center_lat: float | None = None
    center_lon: float | None = None
    radius_km: float | None = Field(None, gt=0)

    bonus_type: IncentiveBonusType
    bonus_multiplier: float | None = Field(None, gt=1.0)
    bonus_flat_cents: int | None = Field(None, gt=0)

    starts_at: datetime
    ends_at: datetime

    max_total_completions: int | None = Field(None, gt=0)
    max_completions_per_driver: int | None = Field(None, gt=0)
    min_driver_rating: float | None = Field(None, ge=1.0, le=5.0)

    @model_validator(mode="after")
    def check_geography(self) -> "CreateIncentiveZoneRequest":
        has_polygon = self.polygon is not None and len(self.polygon) >= 3
        has_circle = (
            self.center_lat is not None
            and self.center_lon is not None
            and self.radius_km is not None
        )
        if not has_polygon and not has_circle:
            raise ValueError(
                "Provide either polygon (≥3 points) or center_lat/center_lon/radius_km."
            )
        return self

    @model_validator(mode="after")
    def check_bonus_fields(self) -> "CreateIncentiveZoneRequest":
        if self.bonus_type == IncentiveBonusType.multiplier:
            if self.bonus_multiplier is None:
                raise ValueError("bonus_multiplier is required for MULTIPLIER zones.")
        elif self.bonus_type == IncentiveBonusType.flat:
            if self.bonus_flat_cents is None:
                raise ValueError("bonus_flat_cents is required for FLAT zones.")
        return self

    @model_validator(mode="after")
    def check_time_window(self) -> "CreateIncentiveZoneRequest":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at.")
        return self


class UpdateIncentiveZoneRequest(BaseModel):
    """Admin request body to update an existing incentive zone (partial update)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    reason: str | None = Field(None, min_length=1)
    polygon: list[dict[str, Any]] | None = None
    center_lat: float | None = None
    center_lon: float | None = None
    radius_km: float | None = Field(None, gt=0)
    bonus_multiplier: float | None = Field(None, gt=1.0)
    bonus_flat_cents: int | None = Field(None, gt=0)
    ends_at: datetime | None = None
    max_total_completions: int | None = Field(None, gt=0)
    max_completions_per_driver: int | None = Field(None, gt=0)
    min_driver_rating: float | None = Field(None, ge=1.0, le=5.0)
    is_active: bool | None = None


class RecordZoneCompletionRequest(BaseModel):
    """Admin/internal request to award a zone bonus for a ride."""

    zone_id: uuid.UUID
    driver_profile_id: int
    ride_id: int
    bonus_amount_cents: int = Field(..., gt=0)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class IncentiveZoneResponse(BaseModel):
    """Public zone detail — returned to drivers and admins."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    reason: str
    polygon: list[dict[str, Any]] | None
    center_lat: float | None
    center_lon: float | None
    radius_km: float | None
    bonus_type: IncentiveBonusType
    bonus_multiplier: float | None
    bonus_flat_cents: int | None
    starts_at: datetime
    ends_at: datetime
    max_total_completions: int | None
    max_completions_per_driver: int | None
    min_driver_rating: float | None
    is_active: bool
    created_at: datetime

    # Human-readable bonus summary (computed, not stored).
    bonus_summary: str = ""

    @classmethod
    def from_zone(cls, zone: object) -> "IncentiveZoneResponse":
        obj = cls.model_validate(zone)
        if obj.bonus_type == IncentiveBonusType.multiplier and obj.bonus_multiplier:
            obj.bonus_summary = f"{obj.bonus_multiplier:.2f}× earnings multiplier"
        elif obj.bonus_type == IncentiveBonusType.flat and obj.bonus_flat_cents:
            obj.bonus_summary = f"${obj.bonus_flat_cents / 100:.2f} flat bonus per ride"
        return obj


class ZoneCompletionResponse(BaseModel):
    """Bonus record for a single zone completion."""

    model_config = {"from_attributes": True}

    id: int
    zone_id: uuid.UUID
    driver_profile_id: int
    ride_id: int
    bonus_amount_cents: int
    bonus_type: IncentiveBonusType
    completed_at: datetime

    bonus_amount_dollars: float = 0.0

    @classmethod
    def from_completion(cls, completion: object) -> "ZoneCompletionResponse":
        obj = cls.model_validate(completion)
        obj.bonus_amount_dollars = round(obj.bonus_amount_cents / 100, 2)
        return obj


class DriverZoneEarningsSummary(BaseModel):
    """Aggregate bonus stats for a driver across all incentive zones."""

    driver_profile_id: int
    total_completions: int
    total_bonus_cents: int
    total_bonus_dollars: float
    zones_participated: int


class ZoneStatsResponse(BaseModel):
    """Admin-facing performance stats for a single zone."""

    zone_id: uuid.UUID
    zone_name: str
    total_completions: int
    total_paid_cents: int
    total_paid_dollars: float
    unique_drivers: int
    is_active: bool
    starts_at: datetime
    ends_at: datetime
    max_total_completions: int | None
    remaining_budget: int | None  # None if no cap
