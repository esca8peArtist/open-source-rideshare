"""Schemas for driver document expiry alerts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["license", "registration", "insurance", "inspection"]


class ExpiringDocumentItem(BaseModel):
    doc_type: DocType
    doc_id: int
    expiry_date: date | None
    days_until_expiry: int | None = Field(
        None,
        description="Negative means already expired. None means no expiry date set.",
    )
    status: str

    model_config = {"from_attributes": True}


class DriverExpiryStatusResponse(BaseModel):
    """Expiry summary for the authenticated driver."""

    driver_id: int
    expiring: list[ExpiringDocumentItem] = Field(
        default_factory=list,
        description="Documents expiring within the requested window.",
    )
    expired: list[ExpiringDocumentItem] = Field(
        default_factory=list,
        description="Documents already past their expiry date.",
    )
    has_issues: bool = Field(
        description="True if any documents are expiring or already expired."
    )

    model_config = {"from_attributes": True}


class AdminExpiringDocumentRow(BaseModel):
    """One row in the admin expiring-documents list."""

    driver_id: int
    doc_type: DocType
    doc_id: int
    expiry_date: date | None
    days_until_expiry: int | None
    status: str

    model_config = {"from_attributes": True}


class AdminExpiringDocumentsResponse(BaseModel):
    """Paginated list of expiring documents across all drivers."""

    items: list[AdminExpiringDocumentRow]
    total: int
    days_ahead: int
    doc_type_filter: DocType | None


class ExpiryScaResponse(BaseModel):
    """Result of a bulk expiry scan."""

    licenses_marked_expired: int
    registrations_marked_expired: int
    insurance_marked_expired: int
    inspections_marked_expired: int
    total_marked_expired: int
