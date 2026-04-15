"""Pydantic schemas for driver tax reporting and 1099-NEC documents."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_tax_document import TaxDocumentStatus, TaxDocumentType, TinType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class W9SubmitRequest(BaseModel):
    """Payload for a driver to submit W-9 information."""

    tin_type: TinType = Field(..., description="SSN or EIN.")
    tin_last4: str = Field(
        ...,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="Last 4 digits of the TIN only — never submit the full TIN.",
    )
    business_name: str | None = Field(
        default=None,
        description="Business name (required when tin_type is EIN).",
    )


class AdminSubmitRequest(BaseModel):
    """Admin payload to mark a document as submitted to the IRS."""

    admin_notes: str | None = Field(default=None, description="Optional admin notes.")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TaxProfileResponse(BaseModel):
    """Driver tax profile returned to clients.

    The full TIN is never exposed — only tin_last4.
    """

    id: int
    driver_profile_id: int
    tin_type: TinType | None
    tin_last4: str | None
    business_name: str | None
    has_w9: bool
    w9_received_at: datetime | None
    is_backup_withholding_exempt: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaxDocumentResponse(BaseModel):
    """Tax document details returned to drivers and admins."""

    id: int
    driver_profile_id: int
    tax_year: int
    document_type: TaxDocumentType
    status: TaxDocumentStatus
    gross_earnings_cents: int
    nonemployee_compensation_cents: int
    rides_count: int
    admin_notes: str | None
    generated_at: datetime | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchGenerateResponse(BaseModel):
    """Result of a batch tax document generation run."""

    tax_year: int
    generated: int
    skipped: int
    errors: int
