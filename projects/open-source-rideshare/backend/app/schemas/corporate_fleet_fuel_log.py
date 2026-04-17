"""Pydantic v2 schemas for Corporate Fleet Fuel & Mileage Tracking.

Fleet managers and drivers log fuel fill-ups for company vehicles.  The
schemas cover write payloads, read responses, and per-vehicle / fleet-wide
fuel analytics summaries.

Public surface
--------------
FuelLogCreate           — payload for recording a fuel fill-up.
FuelLogUpdate           — partial-update payload.
FuelLogResponse         — full fuel log record returned by the API.
VehicleFuelSummary      — fuel analytics for a single fleet vehicle.
FleetFuelSummary        — fleet-wide fuel analytics for a corporate account.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_fuel_log import FleetFuelType


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class FuelLogCreate(BaseModel):
    """Payload for recording a fuel fill-up or energy charge event.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle being filled (required).
        fuel_type: Fuel or energy type (required).
        fill_date: Calendar date of the fill-up (required).
        odometer_miles: Odometer reading at fill time, nullable (ge=0).
        gallons_added: Volume of liquid fuel added in gallons, nullable (ge=0).
        kwh_added: Energy added in kWh for electric vehicles, nullable (ge=0).
        cost_per_unit_usd: Price per gallon or per kWh, nullable (ge=0).
        total_cost_usd: Total amount paid, nullable (ge=0).
        station_name: Name or address of the fill station, nullable.
        notes: Free-text notes, nullable.
    """

    fleet_vehicle_id: uuid.UUID
    fuel_type: FleetFuelType
    fill_date: date
    odometer_miles: Optional[int] = Field(None, ge=0)
    gallons_added: Optional[float] = Field(None, ge=0)
    kwh_added: Optional[float] = Field(None, ge=0)
    cost_per_unit_usd: Optional[float] = Field(None, ge=0)
    total_cost_usd: Optional[float] = Field(None, ge=0)
    station_name: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None


class FuelLogUpdate(BaseModel):
    """Partial-update payload for a fuel log record.

    All fields are optional.  fleet_vehicle_id and account_id cannot be
    changed after creation.
    """

    fuel_type: Optional[FleetFuelType] = None
    fill_date: Optional[date] = None
    odometer_miles: Optional[int] = Field(None, ge=0)
    gallons_added: Optional[float] = Field(None, ge=0)
    kwh_added: Optional[float] = Field(None, ge=0)
    cost_per_unit_usd: Optional[float] = Field(None, ge=0)
    total_cost_usd: Optional[float] = Field(None, ge=0)
    station_name: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schema
# ---------------------------------------------------------------------------


class FuelLogResponse(BaseModel):
    """Full fuel log record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fleet_vehicle_id: uuid.UUID
    account_id: int
    fuel_type: str
    fill_date: date
    odometer_miles: Optional[int]
    gallons_added: Optional[float]
    kwh_added: Optional[float]
    cost_per_unit_usd: Optional[float]
    total_cost_usd: Optional[float]
    station_name: Optional[str]
    notes: Optional[str]
    logged_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Analytics summaries
# ---------------------------------------------------------------------------


class VehicleFuelSummary(BaseModel):
    """Fuel and mileage analytics for a single fleet vehicle.

    Attributes:
        fleet_vehicle_id: UUID of the vehicle.
        log_count: Total number of fuel log records.
        total_cost_usd: Sum of all total_cost_usd values.
        total_gallons: Sum of all gallons_added values.
        total_kwh: Sum of all kwh_added values.
        min_odometer_miles: Earliest odometer reading on record.
        max_odometer_miles: Latest odometer reading on record.
        total_miles_tracked: Difference between max and min odometer (or None).
        avg_mpg: Average MPG computed as total_miles_tracked / total_gallons (or None).
        cost_per_mile_usd: total_cost_usd / total_miles_tracked (or None).
        first_fill_date: Date of the earliest log entry.
        last_fill_date: Date of the most recent log entry.
    """

    fleet_vehicle_id: uuid.UUID
    log_count: int
    total_cost_usd: float
    total_gallons: float
    total_kwh: float
    min_odometer_miles: Optional[int]
    max_odometer_miles: Optional[int]
    total_miles_tracked: Optional[int]
    avg_mpg: Optional[float]
    cost_per_mile_usd: Optional[float]
    first_fill_date: Optional[date]
    last_fill_date: Optional[date]


class FuelTypeBreakdown(BaseModel):
    """Cost and volume totals for a single fuel type."""

    fuel_type: str
    log_count: int
    total_cost_usd: float
    total_gallons: float
    total_kwh: float


class VehicleFuelSummaryAnalytics(BaseModel):
    """Per-vehicle fuel analytics returned by the fuel-log summary endpoint.

    Attributes:
        fleet_vehicle_id: UUID of the vehicle.
        total_fill_ups: Count of log entries.
        total_gallons: Sum of gallons_added (ICE / hybrid vehicles).
        total_kwh: Sum of kwh_added (EV vehicles).
        total_cost_usd: Sum of total_cost_usd across all logs.
        avg_cost_per_gallon_usd: Avg cost_per_unit_usd for gasoline/diesel/hybrid logs.
        avg_cost_per_kwh_usd: Avg cost_per_unit_usd for electric logs.
        last_fill_date: Date of the most recent fill-up.
    """

    fleet_vehicle_id: uuid.UUID
    total_fill_ups: int
    total_gallons: float
    total_kwh: float
    total_cost_usd: float
    avg_cost_per_gallon_usd: Optional[float]
    avg_cost_per_kwh_usd: Optional[float]
    last_fill_date: Optional[date]


class FleetFuelSummary(BaseModel):
    """Fleet-wide fuel analytics for a corporate account.

    Attributes:
        total_logs: Total number of fuel log records across all vehicles.
        total_cost_usd: Sum of all total_cost_usd across all logs.
        total_gallons: Sum of all gallons_added across all logs.
        total_kwh: Sum of all kwh_added across all logs.
        by_fuel_type: Per-type breakdown list.
        vehicle_count: Number of distinct vehicles that have at least one log.
    """

    total_logs: int
    total_cost_usd: float
    total_gallons: float
    total_kwh: float
    by_fuel_type: List[FuelTypeBreakdown]
    vehicle_count: int
