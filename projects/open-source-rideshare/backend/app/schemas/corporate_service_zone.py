"""Pydantic schemas for Corporate Service Zones."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.corporate_service_zone import ZoneAppliesTo, ZoneType


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class ServiceZoneBase(BaseModel):
    """Shared fields used in create and update schemas."""

    name: Optional[str] = Field(
        None, max_length=100, description="Zone name, unique per account"
    )
    description: Optional[str] = Field(
        None, description="Optional description of the zone's purpose"
    )
    zone_type: Optional[ZoneType] = Field(
        None, description="allowed / restricted / approval_required"
    )
    center_latitude: Optional[float] = Field(
        None, ge=-90.0, le=90.0, description="Latitude of zone centre"
    )
    center_longitude: Optional[float] = Field(
        None, ge=-180.0, le=180.0, description="Longitude of zone centre"
    )
    radius_km: Optional[float] = Field(
        None, gt=0, description="Zone radius in kilometres (must be > 0)"
    )
    applies_to: Optional[ZoneAppliesTo] = Field(
        None, description="pickup / dropoff / both"
    )
    group_ids: Optional[list[int]] = Field(
        None, description="Employee group IDs this zone applies to; null = all members"
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class ServiceZoneCreate(ServiceZoneBase):
    """Fields required when creating a new service zone."""

    name: str = Field(..., min_length=1, max_length=100)
    zone_type: ZoneType
    center_latitude: float = Field(..., ge=-90.0, le=90.0)
    center_longitude: float = Field(..., ge=-180.0, le=180.0)
    radius_km: float = Field(..., gt=0)
    applies_to: ZoneAppliesTo = ZoneAppliesTo.both

    @field_validator("radius_km")
    @classmethod
    def radius_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("radius_km must be greater than 0")
        return v


# ---------------------------------------------------------------------------
# Update (all optional — partial PATCH)
# ---------------------------------------------------------------------------


class ServiceZoneUpdate(ServiceZoneBase):
    """All fields optional for partial updates."""

    @field_validator("radius_km")
    @classmethod
    def radius_must_be_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("radius_km must be greater than 0")
        return v


# ---------------------------------------------------------------------------
# Zone check request / response
# ---------------------------------------------------------------------------


class ZoneCheckRequest(BaseModel):
    """Request body for checking if a ride's locations fall within any zones."""

    pickup_latitude: float = Field(..., ge=-90.0, le=90.0)
    pickup_longitude: float = Field(..., ge=-180.0, le=180.0)
    dropoff_latitude: float = Field(..., ge=-90.0, le=90.0)
    dropoff_longitude: float = Field(..., ge=-180.0, le=180.0)
    member_group_ids: Optional[list[int]] = Field(
        None,
        description="Employee group IDs for the requesting member (used to filter group-scoped zones)",
    )


class ZoneMatchDetail(BaseModel):
    """A single zone that matched a ride endpoint."""

    zone_id: int
    zone_name: str
    zone_type: ZoneType
    applies_to: ZoneAppliesTo
    distance_km: float = Field(
        ..., description="Distance in km from the checked point to the zone centre"
    )
    radius_km: float


class ZoneCheckResponse(BaseModel):
    """Result of checking a ride's pickup/dropoff against all active service zones."""

    pickup_matches: list[ZoneMatchDetail]
    dropoff_matches: list[ZoneMatchDetail]
    is_restricted: bool = Field(
        ..., description="True if any restricted zone applies to this ride"
    )
    requires_approval: bool = Field(
        ..., description="True if any approval_required zone applies (and not restricted)"
    )
    denial_reasons: list[str]


# ---------------------------------------------------------------------------
# Coverage summary
# ---------------------------------------------------------------------------


class ZoneCoverageSummary(BaseModel):
    """High-level count of active zones by type for the account."""

    total_active_zones: int
    allowed_count: int
    restricted_count: int
    approval_required_count: int
    pickup_only_count: int
    dropoff_only_count: int
    both_count: int


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class ServiceZoneResponse(BaseModel):
    """Full service zone representation returned to callers."""

    id: int
    account_id: int
    created_by_id: Optional[int]
    name: str
    description: Optional[str]
    zone_type: ZoneType
    center_latitude: float
    center_longitude: float
    radius_km: float
    applies_to: ZoneAppliesTo
    group_ids: Optional[list[int]]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# List response
# ---------------------------------------------------------------------------


class ServiceZoneListResponse(BaseModel):
    """Paginated list of service zones."""

    items: list[ServiceZoneResponse]
    total: int
