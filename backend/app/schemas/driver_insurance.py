"""Pydantic schemas for driver insurance document management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from app.models.driver_insurance import InsuranceDocumentStatus, InsuranceDocumentType


class InsuranceDocumentCreate(BaseModel):
    """Driver-submitted fields for a new insurance document."""

    document_type: InsuranceDocumentType
    insurance_provider: str
    policy_number: str
    coverage_amount: Decimal
    policy_start_date: date
    policy_end_date: date
    document_url: Optional[str] = None

    @field_validator("coverage_amount")
    @classmethod
    def coverage_amount_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("coverage_amount must be non-negative")
        return v

    @model_validator(mode="after")
    def dates_valid(self) -> "InsuranceDocumentCreate":
        if self.policy_end_date <= self.policy_start_date:
            raise ValueError("policy_end_date must be after policy_start_date")
        if self.policy_end_date <= date.today():
            raise ValueError("policy_end_date must be in the future")
        return self


class InsuranceDocumentUpdate(BaseModel):
    """Driver can update fields on a pending document."""

    insurance_provider: Optional[str] = None
    policy_number: Optional[str] = None
    coverage_amount: Optional[Decimal] = None
    policy_start_date: Optional[date] = None
    policy_end_date: Optional[date] = None
    document_url: Optional[str] = None

    @field_validator("coverage_amount")
    @classmethod
    def coverage_amount_non_negative(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError("coverage_amount must be non-negative")
        return v


class InsuranceDocumentResponse(BaseModel):
    """Full document details returned to the driver or admin."""

    id: int
    driver_id: int
    document_type: InsuranceDocumentType
    insurance_provider: str
    policy_number: str
    coverage_amount: Decimal
    policy_start_date: date
    policy_end_date: date
    document_url: Optional[str]
    status: InsuranceDocumentStatus
    rejection_reason: Optional[str]
    verified_by: Optional[int]
    verified_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminReviewRequest(BaseModel):
    """Admin approve or reject a document."""

    status: InsuranceDocumentStatus
    rejection_reason: Optional[str] = None

    @model_validator(mode="after")
    def rejection_reason_required_on_reject(self) -> "AdminReviewRequest":
        if self.status == InsuranceDocumentStatus.REJECTED and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a document")
        allowed = {InsuranceDocumentStatus.APPROVED, InsuranceDocumentStatus.REJECTED}
        if self.status not in allowed:
            raise ValueError("status must be 'approved' or 'rejected'")
        return self


class InsuranceStatusSummary(BaseModel):
    """High-level insurance status for a driver."""

    has_valid_insurance: bool
    days_until_expiry: Optional[int]
    active_document: Optional[InsuranceDocumentResponse]
    documents: list[InsuranceDocumentResponse]
