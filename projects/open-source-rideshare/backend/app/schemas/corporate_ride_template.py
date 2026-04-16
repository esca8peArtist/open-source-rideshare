"""Pydantic schemas for Corporate Ride Templates."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class RideTemplateBase(BaseModel):
    """Shared fields used in create and update schemas."""

    name: Optional[str] = Field(None, max_length=100, description="Template name, unique per account")
    description: Optional[str] = Field(None, description="Optional longer description")

    pickup_location_name: Optional[str] = Field(
        None, max_length=200, description="Friendly name for the pickup point"
    )
    pickup_address_line1: Optional[str] = Field(None, max_length=200)
    pickup_address_line2: Optional[str] = Field(None, max_length=200)
    pickup_city: Optional[str] = Field(None, max_length=100)
    pickup_state: Optional[str] = Field(None, max_length=100)
    pickup_country: Optional[str] = Field(None, max_length=100)
    pickup_postal_code: Optional[str] = Field(None, max_length=20)
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None

    dropoff_location_name: Optional[str] = Field(
        None, max_length=200, description="Friendly name for the dropoff point"
    )
    dropoff_address_line1: Optional[str] = Field(None, max_length=200)
    dropoff_address_line2: Optional[str] = Field(None, max_length=200)
    dropoff_city: Optional[str] = Field(None, max_length=100)
    dropoff_state: Optional[str] = Field(None, max_length=100)
    dropoff_country: Optional[str] = Field(None, max_length=100)
    dropoff_postal_code: Optional[str] = Field(None, max_length=20)
    dropoff_latitude: Optional[float] = None
    dropoff_longitude: Optional[float] = None

    vehicle_type: Optional[str] = Field(
        None, max_length=50, description="Preferred vehicle type, e.g. 'standard', 'premium'"
    )
    default_cost_center_id: Optional[int] = None
    default_trip_purpose_id: Optional[int] = None
    notes: Optional[str] = Field(None, description="Extra notes shown to employees")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class RideTemplateCreate(RideTemplateBase):
    """Fields required when creating a new ride template."""

    name: str = Field(..., min_length=1, max_length=100)
    pickup_location_name: str = Field(..., min_length=1, max_length=200)
    dropoff_location_name: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Update (all optional — partial PATCH)
# ---------------------------------------------------------------------------


class RideTemplateUpdate(RideTemplateBase):
    """All fields optional for partial updates."""


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class RideTemplateResponse(BaseModel):
    """Full ride template representation returned to callers."""

    id: int
    account_id: int
    created_by_id: Optional[int]
    name: str
    description: Optional[str]

    pickup_location_name: str
    pickup_address_line1: Optional[str]
    pickup_address_line2: Optional[str]
    pickup_city: Optional[str]
    pickup_state: Optional[str]
    pickup_country: Optional[str]
    pickup_postal_code: Optional[str]
    pickup_latitude: Optional[float]
    pickup_longitude: Optional[float]

    dropoff_location_name: str
    dropoff_address_line1: Optional[str]
    dropoff_address_line2: Optional[str]
    dropoff_city: Optional[str]
    dropoff_state: Optional[str]
    dropoff_country: Optional[str]
    dropoff_postal_code: Optional[str]
    dropoff_latitude: Optional[float]
    dropoff_longitude: Optional[float]

    vehicle_type: Optional[str]
    default_cost_center_id: Optional[int]
    default_trip_purpose_id: Optional[int]
    notes: Optional[str]
    use_count: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# List response
# ---------------------------------------------------------------------------


class RideTemplateListResponse(BaseModel):
    """Paginated list of ride templates."""

    items: list[RideTemplateResponse]
    total: int
