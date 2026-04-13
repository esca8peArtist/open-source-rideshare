"""Pydantic schemas for vehicle inspection record management."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, model_validator

from app.models.vehicle_inspection import InspectionAlertType, InspectionStatus, InspectionType


class VehicleInspectionCreate(BaseModel):
    """Driver-submitted fields for a new vehicle inspection record."""

    inspection_type: InspectionType
    inspection_date: date
    expiry_date: Optional[date] = None
    document_url: Optional[str] = None
    odometer_reading: Optional[int] = None
    passed_items: Optional[list] = None
    failed_items: Optional[list] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def expiry_after_inspection(self) -> "VehicleInspectionCreate":
        if self.expiry_date is not None and self.expiry_date <= self.inspection_date:
            raise ValueError("expiry_date must be after inspection_date")
        return self


class VehicleInspectionUpdate(BaseModel):
    """Driver can update fields on a pending inspection record."""

    document_url: Optional[str] = None
    odometer_reading: Optional[int] = None
    notes: Optional[str] = None
    passed_items: Optional[list] = None
    failed_items: Optional[list] = None


class VehicleInspectionResponse(BaseModel):
    """Full inspection record details returned to the driver or admin."""

    id: int
    driver_id: int
    inspection_type: InspectionType
    inspection_date: date
    expiry_date: Optional[date]
    status: InspectionStatus
    document_url: Optional[str]
    odometer_reading: Optional[int]
    passed_items: Optional[list]
    failed_items: Optional[list]
    notes: Optional[str]
    rejection_reason: Optional[str]
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminInspectionReview(BaseModel):
    """Admin approve or reject an inspection record."""

    status: InspectionStatus
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def rejection_reason_required_on_reject(self) -> "AdminInspectionReview":
        if self.status == InspectionStatus.REJECTED and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting an inspection")
        allowed = {InspectionStatus.APPROVED, InspectionStatus.REJECTED}
        if self.status not in allowed:
            raise ValueError("status must be 'approved' or 'rejected'")
        return self


class InspectionStatusSummary(BaseModel):
    """High-level inspection status for a driver."""

    has_active_inspection: bool
    days_until_expiry: Optional[int]
    current_inspection: Optional[VehicleInspectionResponse]
    inspections: list[VehicleInspectionResponse]


class VehicleInspectionAlertResponse(BaseModel):
    """Alert record details."""

    id: int
    inspection_id: int
    alert_type: InspectionAlertType
    alert_date: datetime
    acknowledged: bool
    created_at: datetime

    model_config = {"from_attributes": True}
