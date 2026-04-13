"""Pydantic schemas for the lost and found feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.lost_found import LostItemCategory, LostItemStatus


class LostItemReportCreate(BaseModel):
    """Request body for reporting a lost item (rider) or found item (driver).

    ride_id is optional — the reporter may not remember which ride.
    description must be 1–500 characters and category must be a valid enum value.
    """

    ride_id: int | None = Field(None, description="ID of the associated ride, if known")
    description: str = Field(..., min_length=1, max_length=500, description="Description of the item")
    category: LostItemCategory = Field(..., description="Item category")
    color: str | None = Field(None, max_length=100, description="Colour of the item")
    contact_phone: str | None = Field(None, max_length=30, description="Contact phone number")
    contact_email: str | None = Field(None, max_length=255, description="Contact email address")


class LostItemReportResponse(BaseModel):
    """Response body for a lost/found item report."""

    id: int
    ride_id: int | None
    reporter_type: str
    reporter_id: int
    description: str
    category: LostItemCategory
    color: str | None
    status: LostItemStatus
    matched_report_id: int | None
    resolved_at: datetime | None
    resolution_notes: str | None
    admin_id: int | None
    contact_phone: str | None
    contact_email: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MatchReportRequest(BaseModel):
    """Request body for admin matching a found report to a lost report."""

    matched_report_id: int = Field(..., description="ID of the report to link to this one")


class ResolveReportRequest(BaseModel):
    """Request body for admin resolving a report (closing it out).

    status must be one of: returned, donated, discarded.
    """

    status: LostItemStatus = Field(
        ...,
        description="Final status: returned | donated | discarded",
    )
    resolution_notes: str | None = Field(
        None,
        max_length=1000,
        description="Optional notes about the resolution",
    )
