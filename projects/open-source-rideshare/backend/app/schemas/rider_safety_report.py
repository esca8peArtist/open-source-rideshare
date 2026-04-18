"""Pydantic schemas for post-ride rider safety reports.

POST   /riders/me/safety-reports
GET    /riders/me/safety-reports
GET    /riders/me/safety-reports/{report_id}
GET    /admin/safety-reports
POST   /admin/safety-reports/{report_id}/review

Riders file safety reports after a completed ride to flag concerns about driver
behaviour, vehicle condition, routing issues, or other incidents.  Reports are
distinct from panic alerts (which are in-ride emergencies) and from general
complaints (which cover billing/service disputes).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SafetyReportCategory(str, Enum):
    DANGEROUS_DRIVING = "dangerous_driving"
    HARASSMENT = "harassment"
    VEHICLE_ISSUE = "vehicle_issue"
    WRONG_ROUTE = "wrong_route"
    THREATENING_BEHAVIOR = "threatening_behavior"
    OTHER = "other"


class SafetyReportStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    ESCALATED = "escalated"
    CLOSED = "closed"


class SafetyReportCreate(BaseModel):
    """Request body for filing a post-ride safety report."""

    ride_id: int = Field(..., description="ID of the completed ride this report concerns.")
    category: SafetyReportCategory = Field(..., description="Type of safety concern.")
    description: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Rider's account of what happened.",
    )
    location_lat: Optional[float] = Field(
        None,
        description="Latitude of the incident location (optional).",
    )
    location_lng: Optional[float] = Field(
        None,
        description="Longitude of the incident location (optional).",
    )


class SafetyReportResponse(BaseModel):
    """A safety report record returned to riders and admins."""

    id: str = Field(..., description="Unique report identifier (UUID).")
    ride_id: int = Field(..., description="ID of the ride the report concerns.")
    rider_id: int = Field(..., description="ID of the rider who filed the report.")
    driver_id: int = Field(..., description="ID of the driver being reported.")
    category: SafetyReportCategory
    description: str
    status: SafetyReportStatus
    location_lat: Optional[float]
    location_lng: Optional[float]
    filed_at: datetime = Field(..., description="UTC timestamp when the report was filed.")
    reviewed_at: Optional[datetime] = Field(None, description="UTC timestamp of admin review.")
    reviewed_by: Optional[int] = Field(None, description="Admin user ID who reviewed the report.")
    admin_notes: Optional[str] = Field(None, description="Admin review notes.")

    model_config = {"from_attributes": True}


class SafetyReportListResponse(BaseModel):
    """Paginated list of safety reports."""

    total: int = Field(..., description="Total matching reports (before pagination).")
    items: list[SafetyReportResponse]


class AdminReviewReportRequest(BaseModel):
    """Admin request body for reviewing a safety report."""

    review_status: SafetyReportStatus = Field(
        ...,
        description=(
            "New status to set.  Must be 'reviewed', 'escalated', or 'closed'. "
            "Cannot set back to 'pending'."
        ),
    )
    admin_notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Admin notes on the review outcome.",
    )
