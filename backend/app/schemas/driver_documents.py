"""Pydantic schemas for driver license and vehicle registration document management."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from app.models.driver_documents import DocumentStatus, LicenseClass


# ---------------------------------------------------------------------------
# Driver's License schemas
# ---------------------------------------------------------------------------


class DriverLicenseCreate(BaseModel):
    """Driver-submitted fields for a new driver's license record."""

    license_number: str
    state_issued: str
    license_class: LicenseClass
    expiry_date: date
    document_url: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("license_number")
    @classmethod
    def license_number_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("license_number must not be empty")
        return v.strip()

    @field_validator("state_issued")
    @classmethod
    def state_issued_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("state_issued must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def expiry_in_future(self) -> "DriverLicenseCreate":
        if self.expiry_date <= date.today():
            raise ValueError("expiry_date must be in the future")
        return self


class DriverLicenseUpdate(BaseModel):
    """Driver can update fields on a pending license record."""

    license_number: Optional[str] = None
    state_issued: Optional[str] = None
    license_class: Optional[LicenseClass] = None
    expiry_date: Optional[date] = None
    document_url: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("license_number")
    @classmethod
    def license_number_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("license_number must not be empty")
        return v.strip() if v else v

    @field_validator("state_issued")
    @classmethod
    def state_issued_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("state_issued must not be empty")
        return v.strip() if v else v


class DriverLicenseResponse(BaseModel):
    """Full license record details returned to the driver or admin."""

    id: int
    driver_id: int
    license_number: str
    state_issued: str
    license_class: LicenseClass
    expiry_date: date
    document_url: Optional[str]
    status: DocumentStatus
    notes: Optional[str]
    rejection_reason: Optional[str]
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    uploaded_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminLicenseReview(BaseModel):
    """Admin approve or reject a driver's license document."""

    status: DocumentStatus
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def rejection_reason_required_on_reject(self) -> "AdminLicenseReview":
        if self.status == DocumentStatus.REJECTED and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a document")
        allowed = {DocumentStatus.APPROVED, DocumentStatus.REJECTED}
        if self.status not in allowed:
            raise ValueError("status must be 'approved' or 'rejected'")
        return self


class LicenseStatusSummary(BaseModel):
    """High-level driver's license status for a driver."""

    has_valid_license: bool
    days_until_expiry: Optional[int]
    active_license: Optional[DriverLicenseResponse]
    licenses: list[DriverLicenseResponse]


# ---------------------------------------------------------------------------
# Vehicle Registration schemas
# ---------------------------------------------------------------------------


class VehicleRegistrationCreate(BaseModel):
    """Driver-submitted fields for a new vehicle registration record."""

    vehicle_id: Optional[str] = None
    plate_number: str
    state: str
    expiry_date: date
    document_url: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("plate_number")
    @classmethod
    def plate_number_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plate_number must not be empty")
        return v.strip()

    @field_validator("state")
    @classmethod
    def state_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("state must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def expiry_in_future(self) -> "VehicleRegistrationCreate":
        if self.expiry_date <= date.today():
            raise ValueError("expiry_date must be in the future")
        return self


class VehicleRegistrationUpdate(BaseModel):
    """Driver can update fields on a pending vehicle registration record."""

    vehicle_id: Optional[str] = None
    plate_number: Optional[str] = None
    state: Optional[str] = None
    expiry_date: Optional[date] = None
    document_url: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("plate_number")
    @classmethod
    def plate_number_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("plate_number must not be empty")
        return v.strip() if v else v

    @field_validator("state")
    @classmethod
    def state_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("state must not be empty")
        return v.strip() if v else v


class VehicleRegistrationResponse(BaseModel):
    """Full registration record details returned to the driver or admin."""

    id: int
    driver_id: int
    vehicle_id: Optional[str]
    plate_number: str
    state: str
    expiry_date: date
    document_url: Optional[str]
    status: DocumentStatus
    notes: Optional[str]
    rejection_reason: Optional[str]
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    uploaded_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminRegistrationReview(BaseModel):
    """Admin approve or reject a vehicle registration document."""

    status: DocumentStatus
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def rejection_reason_required_on_reject(self) -> "AdminRegistrationReview":
        if self.status == DocumentStatus.REJECTED and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a document")
        allowed = {DocumentStatus.APPROVED, DocumentStatus.REJECTED}
        if self.status not in allowed:
            raise ValueError("status must be 'approved' or 'rejected'")
        return self


class RegistrationStatusSummary(BaseModel):
    """High-level vehicle registration status for a driver."""

    has_valid_registration: bool
    days_until_expiry: Optional[int]
    active_registration: Optional[VehicleRegistrationResponse]
    registrations: list[VehicleRegistrationResponse]


# ---------------------------------------------------------------------------
# Combined summary schema
# ---------------------------------------------------------------------------


class DriverDocumentsSummary(BaseModel):
    """Combined license and registration status for a driver."""

    license_summary: LicenseStatusSummary
    registration_summary: RegistrationStatusSummary
