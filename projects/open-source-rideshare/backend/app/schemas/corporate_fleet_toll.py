"""Pydantic v2 schemas for Corporate Fleet Toll & Transponder Management.

Fleet managers track toll transponders assigned to fleet vehicles and log
individual toll charges for cost analytics.

Public surface
--------------
TransponderCreate           — payload for assigning a new transponder.
TransponderResponse         — full transponder record returned by the API.
TollChargeCreate            — payload for logging a toll charge.
TollChargeUpdate            — partial-update payload for a toll charge.
TollChargeResponse          — full toll charge record returned by the API.
VehicleTollSummaryResponse  — aggregate toll stats for a single vehicle.
FleetTollSummaryResponse    — fleet-wide aggregate toll stats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_toll import TransponderProvider


# ---------------------------------------------------------------------------
# Transponder schemas
# ---------------------------------------------------------------------------


class TransponderCreate(BaseModel):
    """Payload for assigning a toll transponder to a fleet vehicle.

    Attributes:
        fleet_vehicle_id: UUID of the target fleet vehicle (required).
        transponder_number: Transponder device number (required, 1–100 chars).
        provider: Toll authority / transponder network enum (required).
        assigned_date: Date the transponder was assigned (required).
        monthly_plan_cost_usd: Fixed monthly plan fee in USD, nullable.
        toll_account_number: Toll authority account number, nullable (1–100 chars).
        notes: Optional free-text notes.
    """

    fleet_vehicle_id: uuid.UUID
    transponder_number: str = Field(..., min_length=1, max_length=100)
    provider: TransponderProvider
    assigned_date: date
    monthly_plan_cost_usd: Optional[float] = Field(None, ge=0)
    toll_account_number: Optional[str] = Field(None, min_length=1, max_length=100)
    notes: Optional[str] = None


class TransponderResponse(BaseModel):
    """Full toll transponder record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    transponder_number: str
    provider: TransponderProvider
    assigned_date: date
    removed_date: Optional[date]
    monthly_plan_cost_usd: Optional[float]
    toll_account_number: Optional[str]
    is_active: bool
    notes: Optional[str]
    assigned_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Toll charge schemas
# ---------------------------------------------------------------------------


class TollChargeCreate(BaseModel):
    """Payload for logging an individual toll charge.

    Attributes:
        fleet_vehicle_id: UUID of the vehicle (required).
        transponder_id: UUID of the transponder used, nullable.
        charge_date: Date when the toll was charged (required).
        plaza_name: Name of the toll plaza or bridge, nullable (1–200 chars).
        amount_usd: Toll amount in USD (required, >= 0).
        entry_location: Entry point description, nullable (1–200 chars).
        exit_location: Exit point description, nullable (1–200 chars).
        trip_purpose: Business purpose of the trip, nullable (1–200 chars).
        notes: Optional free-text notes.
    """

    fleet_vehicle_id: uuid.UUID
    transponder_id: Optional[uuid.UUID] = None
    charge_date: date
    plaza_name: Optional[str] = Field(None, min_length=1, max_length=200)
    amount_usd: float = Field(..., ge=0)
    entry_location: Optional[str] = Field(None, min_length=1, max_length=200)
    exit_location: Optional[str] = Field(None, min_length=1, max_length=200)
    trip_purpose: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None


class TollChargeUpdate(BaseModel):
    """Partial-update payload for a toll charge record.

    All fields are optional.  fleet_vehicle_id cannot be changed once created.
    """

    transponder_id: Optional[uuid.UUID] = None
    charge_date: Optional[date] = None
    plaza_name: Optional[str] = Field(None, min_length=1, max_length=200)
    amount_usd: Optional[float] = Field(None, ge=0)
    entry_location: Optional[str] = Field(None, min_length=1, max_length=200)
    exit_location: Optional[str] = Field(None, min_length=1, max_length=200)
    trip_purpose: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None


class TollChargeResponse(BaseModel):
    """Full toll charge record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    transponder_id: Optional[uuid.UUID]
    charge_date: date
    plaza_name: Optional[str]
    amount_usd: float
    entry_location: Optional[str]
    exit_location: Optional[str]
    trip_purpose: Optional[str]
    notes: Optional[str]
    logged_by_id: Optional[int]
    created_at: datetime


# ---------------------------------------------------------------------------
# Summary schemas
# ---------------------------------------------------------------------------


class VehicleTollSummaryResponse(BaseModel):
    """Aggregate toll statistics for a single fleet vehicle.

    Attributes:
        fleet_vehicle_id: UUID of the vehicle.
        charge_count: Number of toll charge records.
        total_cost_usd: Sum of all toll charges in USD.
        active_transponder_count: Number of currently active transponders.
        date_from: Earliest charge date in the result set, nullable.
        date_to: Latest charge date in the result set, nullable.
    """

    fleet_vehicle_id: uuid.UUID
    charge_count: int
    total_cost_usd: float
    active_transponder_count: int
    date_from: Optional[date]
    date_to: Optional[date]


class FleetTollVehicleBreakdown(BaseModel):
    """Per-vehicle toll cost entry used inside FleetTollSummaryResponse."""

    fleet_vehicle_id: uuid.UUID
    charge_count: int
    total_cost_usd: float


class FleetTollSummaryResponse(BaseModel):
    """Fleet-wide aggregate toll statistics for a corporate account.

    Attributes:
        total_charge_count: Total number of toll charge records.
        total_cost_usd: Sum of all toll charges in USD.
        active_transponder_count: Number of currently active transponders.
        vehicle_count: Number of distinct vehicles with charges.
        per_provider_cost_usd: Cost breakdown keyed by provider name.
        top_vehicles: Top vehicles by toll cost (up to 10).
    """

    total_charge_count: int
    total_cost_usd: float
    active_transponder_count: int
    vehicle_count: int
    per_provider_cost_usd: Dict[str, float]
    top_vehicles: List[FleetTollVehicleBreakdown]
