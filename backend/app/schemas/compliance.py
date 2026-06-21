"""Pydantic schemas for the compliance API.

All response models are read-only; compliance records are managed by admin
actions and nightly cron — riders and drivers never write directly.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, field_validator

from app.models.driver import MembershipStatus
from app.services.compliance import ComplianceField, ComplianceIssue, ComplianceResult


# ── Compliance check response ────────────────────────────────────────────────

class ComplianceIssueResponse(BaseModel):
    """A single compliance problem returned to API callers."""

    field: ComplianceField
    message: str
    days_until_expiry: int | None = None


class ComplianceCheckResponse(BaseModel):
    """Result of ``GET /api/v1/compliance/check/{driver_id}``.

    ``eligible`` is the single authoritative gate value: if False, the driver
    must not be allowed to go online regardless of which issues are present.
    """

    driver_id: int
    eligible: bool
    issues: list[ComplianceIssueResponse]
    checked_at: datetime

    @classmethod
    def from_result(cls, result: ComplianceResult) -> "ComplianceCheckResponse":
        return cls(
            driver_id=result.driver_id,
            eligible=result.eligible,
            issues=[
                ComplianceIssueResponse(
                    field=issue.field,
                    message=issue.message,
                    days_until_expiry=issue.days_until_expiry,
                )
                for issue in result.issues
            ],
            checked_at=result.checked_at,
        )


# ── Jurisdiction response ────────────────────────────────────────────────────

class JurisdictionResponse(BaseModel):
    """Public view of a jurisdiction's regulatory configuration."""

    id: str
    name: str
    background_check_type: str
    per_trip_surcharge: float
    per_trip_surcharge_description: str
    license_requirement: str
    insurance_requirement: str
    wav_mandate: bool
    wav_percentage: float
    license_grace_days: int
    background_check_grace_days: int
    is_active: bool

    model_config = {"from_attributes": True}


# ── Admin: update membership status ──────────────────────────────────────────

class MembershipStatusUpdateRequest(BaseModel):
    """Body for ``POST /api/v1/admin/drivers/{driver_id}/membership-status``.

    ``reason`` is required so that every status change has an audit trail
    entry explaining why it was made.
    """

    new_status: MembershipStatus
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must not be empty")
        return v.strip()


class MembershipStatusUpdateResponse(BaseModel):
    """Confirmation returned after a successful membership status update."""

    driver_id: int
    previous_status: MembershipStatus
    new_status: MembershipStatus
    reason: str
    updated_at: datetime


# ── Admin: update compliance document expiry dates ───────────────────────────

class ComplianceDocumentUpdate(BaseModel):
    """Body for ``PATCH /api/v1/admin/drivers/{driver_id}/compliance-documents``.

    All fields are optional — supply only those you are updating.
    Dates must be in the future; the API rejects back-dated entries to
    prevent accidental data corruption.
    """

    license_expiry: date | None = None
    background_check_expiry: date | None = None
    vehicle_inspection_expiry: date | None = None
    insurance_endorsement_expiry: date | None = None

    @field_validator(
        "license_expiry",
        "background_check_expiry",
        "vehicle_inspection_expiry",
        "insurance_endorsement_expiry",
    )
    @classmethod
    def expiry_not_in_past(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("Expiry date must not be in the past")
        return v


class ComplianceDocumentUpdateResponse(BaseModel):
    """Confirmation returned after updating compliance document expiry dates."""

    driver_id: int
    license_expiry: date | None = None
    background_check_expiry: date | None = None
    vehicle_inspection_expiry: date | None = None
    insurance_endorsement_expiry: date | None = None
    updated_at: datetime
