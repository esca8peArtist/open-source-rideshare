"""Pydantic v2 schemas for Corporate Fleet Vehicle Management.

Corporate accounts can define a pool of company-owned/leased vehicles and
assign drivers to them.

Public surface
--------------
FleetVehicleCreate      — payload for creating a fleet vehicle.
FleetVehicleUpdate      — partial-update payload.
FleetVehicleResponse    — full fleet vehicle record returned by the API.
FleetAssignmentCreate   — payload for assigning a driver to a vehicle.
FleetAssignmentResponse — full assignment record returned by the API.
FleetSummaryResponse    — aggregate counts for a corporate fleet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Allowed vehicle type values
# ---------------------------------------------------------------------------

ALLOWED_VEHICLE_TYPES: frozenset[str] = frozenset(
    {"sedan", "suv", "van", "minivan", "truck", "other"}
)

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class FleetVehicleCreate(BaseModel):
    """Payload for creating a corporate fleet vehicle.

    Attributes:
        name: Human-readable label for the vehicle (required).
        vehicle_type: Category — sedan/suv/van/minivan/truck/other.
        make: Manufacturer name.
        model_name: Model name.
        year: Model year.
        license_plate: License plate number.
        color: Vehicle colour.
        capacity: Passenger capacity (default 4).
        is_wav: Whether the vehicle is wheelchair-accessible (default False).
        notes: Free-text notes for fleet managers.
    """

    name: str = Field(..., min_length=1, max_length=100)
    vehicle_type: Optional[str] = Field(None, max_length=50)
    make: Optional[str] = Field(None, max_length=50)
    model_name: Optional[str] = Field(None, max_length=50)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    license_plate: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=30)
    capacity: int = Field(4, ge=1, le=100)
    is_wav: bool = False
    notes: Optional[str] = None


class FleetVehicleUpdate(BaseModel):
    """Partial-update payload for a corporate fleet vehicle.

    All fields are optional.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    vehicle_type: Optional[str] = Field(None, max_length=50)
    make: Optional[str] = Field(None, max_length=50)
    model_name: Optional[str] = Field(None, max_length=50)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    license_plate: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=30)
    capacity: Optional[int] = Field(None, ge=1, le=100)
    is_wav: Optional[bool] = None
    notes: Optional[str] = None


class FleetAssignmentCreate(BaseModel):
    """Payload for assigning a driver to a fleet vehicle.

    Attributes:
        driver_profile_id: ID of the driver profile to assign.  May be None
            to record an unassigned vehicle slot.
        notes: Optional notes on the assignment.
    """

    driver_profile_id: Optional[int] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class FleetVehicleResponse(BaseModel):
    """Full fleet vehicle record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    name: str
    vehicle_type: Optional[str]
    make: Optional[str]
    model_name: Optional[str]
    year: Optional[int]
    license_plate: Optional[str]
    color: Optional[str]
    capacity: int
    is_wav: bool
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class FleetAssignmentResponse(BaseModel):
    """Full fleet assignment record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fleet_vehicle_id: uuid.UUID
    account_id: int
    driver_profile_id: Optional[int]
    assigned_by_id: Optional[int]
    is_active: bool
    notes: Optional[str]
    created_at: datetime


class FleetSummaryResponse(BaseModel):
    """Aggregate fleet statistics for a corporate account.

    Attributes:
        total_vehicles: Total number of vehicles in the fleet.
        active_vehicles: Number of currently active vehicles.
        inactive_vehicles: Number of deactivated vehicles.
        wav_count: Number of wheelchair-accessible vehicles.
        unassigned_count: Number of active vehicles without a current driver.
        by_type: Vehicle counts broken down by vehicle_type.
    """

    total_vehicles: int
    active_vehicles: int
    inactive_vehicles: int
    wav_count: int
    unassigned_count: int
    by_type: dict[str, int]
