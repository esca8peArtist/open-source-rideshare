"""Pydantic schemas for the lost and found system.

Separate request/response schemas are provided for lost item reports
(submitted by riders) and found item reports (submitted by drivers).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.lost_and_found import (
    ContactPreference,
    ItemCategory,
    LafFoundItemStatus,
    LafLostItemStatus,
)


# ---------------------------------------------------------------------------
# Lost item schemas (rider-facing)
# ---------------------------------------------------------------------------


class LostItemReportCreate(BaseModel):
    """Request body for a rider reporting a lost item."""

    ride_id: int | None = Field(
        None,
        description="ID of the ride during which the item was lost. Optional.",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Description of the lost item.",
    )
    category: ItemCategory = Field(..., description="Category of the lost item.")
    date_lost: date = Field(..., description="Date the item was lost.")
    contact_preference: ContactPreference = Field(
        ..., description="How the rider prefers to be contacted."
    )


class FoundItemReportSummary(BaseModel):
    """Minimal view of a matched found report embedded in a lost report response."""

    id: int
    driver_id: int
    description: str
    category: ItemCategory
    storage_location: str
    status: LafFoundItemStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class LostItemReportResponse(BaseModel):
    """Full response body for a lost item report."""

    id: int
    ride_id: int | None
    rider_id: int
    description: str
    category: ItemCategory
    date_lost: date
    contact_preference: ContactPreference
    status: LafLostItemStatus
    matched_found_report_id: int | None
    matched_found_report: FoundItemReportSummary | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LostReportListResponse(BaseModel):
    """Paginated list of lost item reports."""

    items: list[LostItemReportResponse]
    total: int


# ---------------------------------------------------------------------------
# Found item schemas (driver-facing)
# ---------------------------------------------------------------------------


class FoundItemReportCreate(BaseModel):
    """Request body for a driver reporting a found item."""

    ride_id: int | None = Field(
        None,
        description="ID of the ride during which the item was found. Optional.",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Description of the found item.",
    )
    category: ItemCategory = Field(..., description="Category of the found item.")
    date_found: date = Field(..., description="Date the item was found.")
    storage_location: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Where the driver is currently keeping the item.",
    )


class LostItemReportSummary(BaseModel):
    """Minimal view of a matched lost report embedded in a found report response."""

    id: int
    rider_id: int
    description: str
    category: ItemCategory
    status: LafLostItemStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class FoundItemReportResponse(BaseModel):
    """Full response body for a found item report."""

    id: int
    ride_id: int | None
    driver_id: int
    description: str
    category: ItemCategory
    date_found: date
    storage_location: str
    status: LafFoundItemStatus
    matched_lost_report_id: int | None
    matched_lost_report_ref: LostItemReportSummary | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FoundReportListResponse(BaseModel):
    """Paginated list of found item reports."""

    items: list[FoundItemReportResponse]
    total: int


# ---------------------------------------------------------------------------
# Admin action schemas
# ---------------------------------------------------------------------------


class MatchReportsRequest(BaseModel):
    """Admin request to link a lost report to a found report."""

    lost_report_id: int = Field(..., description="ID of the lost item report.")
    found_report_id: int = Field(..., description="ID of the found item report.")
