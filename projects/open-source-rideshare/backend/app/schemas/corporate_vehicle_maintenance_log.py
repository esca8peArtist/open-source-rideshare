"""Pydantic v2 schemas for Corporate Vehicle Maintenance Log.

Fleet managers track service history for company vehicles and schedule
upcoming maintenance with optional next-due date/odometer alerts.

Public surface
--------------
MaintenanceLogCreate        — payload for creating a maintenance record.
MaintenanceLogUpdate        — partial-update payload.
MaintenanceLogComplete      — payload for marking a record as completed.
MaintenanceLogResponse      — full maintenance record returned by the API.
MaintenanceUpcomingResponse — lightweight upcoming-maintenance alert entry.
MaintenanceSummaryResponse  — aggregate counts and totals per account.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_vehicle_maintenance_log import MaintenanceType

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class MaintenanceLogCreate(BaseModel):
    """Payload for creating a vehicle maintenance record.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle (required).
        maintenance_type: Category of maintenance (required).
        title: Short label for the record (required).
        description: Optional detailed notes.
        scheduled_date: When the service is planned (timezone-aware).
        odometer_miles: Current vehicle mileage, nullable.
        cost_usd: Estimated or actual cost, nullable.
        vendor_name: Service centre / vendor name, nullable.
        notes: Additional free-text notes.
        next_due_date: When the next service of this type is due, nullable.
        next_due_odometer: Mileage at which next service is due, nullable.
    """

    fleet_vehicle_id: uuid.UUID
    maintenance_type: MaintenanceType
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    odometer_miles: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[float] = Field(None, ge=0)
    vendor_name: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None
    next_due_date: Optional[datetime] = None
    next_due_odometer: Optional[int] = Field(None, ge=0)


class MaintenanceLogUpdate(BaseModel):
    """Partial-update payload for a maintenance record.

    All fields are optional.  fleet_vehicle_id cannot be changed once created.
    """

    maintenance_type: Optional[MaintenanceType] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    odometer_miles: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[float] = Field(None, ge=0)
    vendor_name: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None
    next_due_date: Optional[datetime] = None
    next_due_odometer: Optional[int] = Field(None, ge=0)


class MaintenanceLogComplete(BaseModel):
    """Payload for marking a maintenance record as completed.

    Attributes:
        completed_at: When the service was completed (defaults to now if omitted).
        odometer_miles: Vehicle mileage at completion, nullable.
        cost_usd: Actual cost of the service, nullable.
        vendor_name: Name of the service centre / vendor, nullable.
        notes: Any additional notes on the completed service.
        next_due_date: When the next service of this type is due, nullable.
        next_due_odometer: Mileage at which next service is due, nullable.
    """

    completed_at: Optional[datetime] = None
    odometer_miles: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[float] = Field(None, ge=0)
    vendor_name: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None
    next_due_date: Optional[datetime] = None
    next_due_odometer: Optional[int] = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class MaintenanceLogResponse(BaseModel):
    """Full vehicle maintenance record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    maintenance_type: str
    title: str
    description: Optional[str]
    scheduled_date: Optional[datetime]
    completed_at: Optional[datetime]
    odometer_miles: Optional[int]
    cost_usd: Optional[float]
    vendor_name: Optional[str]
    notes: Optional[str]
    is_completed: bool
    next_due_date: Optional[datetime]
    next_due_odometer: Optional[int]
    created_by_id: Optional[int]
    completed_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class MaintenanceUpcomingResponse(BaseModel):
    """A lightweight upcoming-maintenance alert for a fleet vehicle.

    Attributes:
        log_id: UUID of the maintenance log record.
        fleet_vehicle_id: UUID of the vehicle.
        maintenance_type: Category of the upcoming service.
        title: Short label for the record.
        next_due_date: When the service is due (timezone-aware).
        days_until_due: Whole days remaining until due_date from today.
        next_due_odometer: Mileage threshold for the next service, nullable.
    """

    log_id: uuid.UUID
    fleet_vehicle_id: uuid.UUID
    maintenance_type: str
    title: str
    next_due_date: datetime
    days_until_due: int
    next_due_odometer: Optional[int]


class MaintenanceSummaryResponse(BaseModel):
    """Aggregate maintenance statistics for a corporate account.

    Attributes:
        total_records: Total number of maintenance records.
        completed: Number of completed records.
        pending: Number of records not yet completed.
        overdue: Records where next_due_date is in the past and not completed.
        due_within_30_days: Records due within the next 30 days (not completed).
        total_cost_usd: Sum of all recorded costs across the account.
        by_type: Record count keyed by maintenance_type value.
    """

    total_records: int
    completed: int
    pending: int
    overdue: int
    due_within_30_days: int
    total_cost_usd: float
    by_type: dict
