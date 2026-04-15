from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.vehicle_maintenance import MaintenanceType


class MaintenanceLogCreate(BaseModel):
    maintenance_type: MaintenanceType
    description: str | None = None
    service_provider: str | None = Field(None, max_length=200)
    notes: str | None = None
    date_serviced: date
    mileage_at_service: int | None = Field(None, ge=0)
    cost_usd: float | None = Field(None, ge=0)
    next_service_date: date | None = None
    next_service_mileage: int | None = Field(None, ge=0)


class MaintenanceLogResponse(BaseModel):
    id: int
    vehicle_id: int
    driver_profile_id: int
    maintenance_type: MaintenanceType
    description: str | None
    service_provider: str | None
    notes: str | None
    date_serviced: date
    mileage_at_service: int | None
    cost_usd: float | None
    next_service_date: date | None
    next_service_mileage: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MaintenanceHistoryResponse(BaseModel):
    logs: list[MaintenanceLogResponse]
    total: int


class UpcomingMaintenanceItem(BaseModel):
    """A single upcoming-or-overdue maintenance alert."""

    log_id: int
    vehicle_id: int
    maintenance_type: MaintenanceType
    next_service_date: date | None
    next_service_mileage: int | None
    days_until_due: int | None  # negative = overdue; None if date not set
    is_overdue: bool


class UpcomingMaintenanceResponse(BaseModel):
    items: list[UpcomingMaintenanceItem]
    total: int


class FleetMaintenanceSummary(BaseModel):
    """Admin-level fleet maintenance overview."""

    total_logs: int
    overdue_count: int
    due_within_30_days: int
    vehicles_with_overdue: int
    recent_logs: list[MaintenanceLogResponse]
