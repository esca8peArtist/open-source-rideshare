"""Pydantic v2 schemas for Corporate Fleet Maintenance Scheduling.

Fleet managers schedule preventive maintenance and log completed service
records for company vehicles.

Public surface
--------------
MaintenanceRecordCreate          — payload for scheduling a maintenance record.
MaintenanceRecordUpdate          — partial-update payload.
MaintenanceRecordResponse        — full maintenance record returned by the API.
VehicleMaintenanceSummaryResponse — per-vehicle aggregate stats.
AccountMaintenanceSummaryResponse — account-wide aggregate stats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_maintenance import FleetMaintenanceStatus, FleetMaintenanceType

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class MaintenanceRecordCreate(BaseModel):
    """Payload for scheduling a fleet vehicle maintenance record.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle (required).
        maintenance_type: Type of maintenance service to be performed (required).
        scheduled_date: Date the service is scheduled for, optional.
        description: Short description of the work to be performed, optional.
        vendor_name: Service vendor or shop name, optional.
        cost_usd: Estimated or actual cost in USD, optional.
        odometer_at_service: Odometer reading at time of service, optional.
        next_service_odometer: Odometer reading for the next service interval, optional.
        next_service_date: Date for the next service of this type, optional.
    """

    fleet_vehicle_id: uuid.UUID
    maintenance_type: FleetMaintenanceType
    scheduled_date: Optional[date] = None
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    vendor_name: Optional[str] = Field(None, min_length=1, max_length=200)
    cost_usd: Optional[float] = Field(None, ge=0)
    odometer_at_service: Optional[int] = Field(None, ge=0)
    next_service_odometer: Optional[int] = Field(None, ge=0)
    next_service_date: Optional[date] = None


class MaintenanceRecordUpdate(BaseModel):
    """Partial-update payload for a fleet maintenance record.

    All fields are optional.
    """

    maintenance_type: Optional[FleetMaintenanceType] = None
    status: Optional[FleetMaintenanceStatus] = None
    scheduled_date: Optional[date] = None
    completed_date: Optional[date] = None
    odometer_at_service: Optional[int] = Field(None, ge=0)
    next_service_odometer: Optional[int] = Field(None, ge=0)
    next_service_date: Optional[date] = None
    cost_usd: Optional[float] = Field(None, ge=0)
    vendor_name: Optional[str] = Field(None, min_length=1, max_length=200)
    technician_name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class MaintenanceRecordResponse(BaseModel):
    """Full fleet maintenance record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    maintenance_type: FleetMaintenanceType
    status: FleetMaintenanceStatus
    scheduled_date: Optional[date]
    completed_date: Optional[date]
    odometer_at_service: Optional[int]
    next_service_odometer: Optional[int]
    next_service_date: Optional[date]
    cost_usd: Optional[float]
    vendor_name: Optional[str]
    technician_name: Optional[str]
    description: Optional[str]
    notes: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class MaintenanceTypeBreakdown(BaseModel):
    """Per-type breakdown entry for vehicle maintenance summary.

    Attributes:
        maintenance_type: The type of maintenance.
        count: Number of records for this type.
        total_cost_usd: Sum of costs for this type.
    """

    maintenance_type: FleetMaintenanceType
    count: int
    total_cost_usd: float


class VehicleMaintenanceSummaryResponse(BaseModel):
    """Aggregate maintenance statistics for a single fleet vehicle.

    Attributes:
        vehicle_id: UUID of the fleet vehicle.
        total_records: Total number of maintenance records for this vehicle.
        total_cost_usd: Sum of all recorded maintenance costs.
        last_service_date: Most recent completed_date across all records, nullable.
        next_scheduled_date: Earliest upcoming scheduled_date, nullable.
        overdue_count: Number of records with status=overdue.
        per_type: Per-maintenance-type breakdown list.
    """

    vehicle_id: uuid.UUID
    total_records: int
    total_cost_usd: float
    last_service_date: Optional[date]
    next_scheduled_date: Optional[date]
    overdue_count: int
    per_type: List[MaintenanceTypeBreakdown]


class AccountMaintenanceSummaryResponse(BaseModel):
    """Account-wide aggregate maintenance statistics.

    Attributes:
        account_id: Corporate account ID.
        total_records: Total maintenance records for this account.
        total_cost_usd: Sum of all recorded maintenance costs across all vehicles.
        overdue_count: Number of records with status=overdue across all vehicles.
        vehicles_with_overdue: List of vehicle UUIDs that have at least one overdue record.
    """

    account_id: int
    total_records: int
    total_cost_usd: float
    overdue_count: int
    vehicles_with_overdue: List[uuid.UUID]
