"""Pydantic schemas for post-ride driver safety reports.

POST   /drivers/me/safety-reports
GET    /drivers/me/safety-reports
GET    /drivers/me/safety-reports/{report_id}
GET    /admin/driver-safety-reports
GET    /admin/driver-safety-reports/stats
POST   /admin/driver-safety-reports/{report_id}/review

Drivers file safety reports after a completed ride to flag concerning rider
behaviour: threats, assault, property damage, fraud, or other safety incidents.
Reports are distinct from general complaints and from in-ride panic alerts.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DriverReportCategory(str, Enum):
    THREATENING_BEHAVIOR = "threatening_behavior"
    PHYSICAL_ASSAULT = "physical_assault"
    PROPERTY_DAMAGE = "property_damage"
    HARASSMENT = "harassment"
    FRAUD = "fraud"
    DANGEROUS_BEHAVIOR = "dangerous_behavior"
    OTHER = "other"


class DriverReportStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    ESCALATED = "escalated"
    CLOSED = "closed"


class DriverSafetyReportCreate(BaseModel):
    """Request body for filing a post-ride driver safety report."""

    ride_id: int = Field(..., description="ID of the completed ride this report concerns.")
    category: DriverReportCategory = Field(..., description="Type of safety concern.")
    description: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Driver's account of what happened.",
    )
    location_lat: Optional[float] = Field(
        None,
        description="Latitude of the incident location (optional).",
    )
    location_lng: Optional[float] = Field(
        None,
        description="Longitude of the incident location (optional).",
    )


class DriverSafetyReportResponse(BaseModel):
    """A driver safety report record returned to drivers and admins."""

    id: str = Field(..., description="Unique report identifier (UUID).")
    ride_id: int = Field(..., description="ID of the ride the report concerns.")
    driver_id: int = Field(..., description="ID of the driver who filed the report.")
    rider_id: int = Field(..., description="ID of the rider being reported.")
    category: DriverReportCategory
    description: str
    status: DriverReportStatus
    location_lat: Optional[float]
    location_lng: Optional[float]
    filed_at: datetime = Field(..., description="UTC timestamp when the report was filed.")
    reviewed_at: Optional[datetime] = Field(None, description="UTC timestamp of admin review.")
    reviewed_by: Optional[int] = Field(None, description="Admin user ID who reviewed the report.")
    admin_notes: Optional[str] = Field(None, description="Admin review notes.")

    model_config = {"from_attributes": True}


class DriverSafetyReportListResponse(BaseModel):
    """Paginated list of driver safety reports."""

    total: int = Field(..., description="Total matching reports (before pagination).")
    items: list[DriverSafetyReportResponse]


class AdminReviewDriverReportRequest(BaseModel):
    """Admin request body for reviewing a driver safety report."""

    review_status: DriverReportStatus = Field(
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


class DriverSafetyReportStats(BaseModel):
    """Aggregate statistics for admin driver safety report dashboard."""

    total_reports: int = Field(..., description="All-time total number of driver safety reports.")
    by_status: dict[str, int] = Field(
        ...,
        description="Count of reports per status (pending, reviewed, escalated, closed).",
    )
    by_category: dict[str, int] = Field(
        ...,
        description="Count of reports per category.",
    )
    escalation_rate: float = Field(
        ...,
        description=(
            "Fraction of total reports that have been escalated.  "
            "0.0 when there are no reports."
        ),
    )
    reports_last_7_days: int = Field(
        ...,
        description="Number of reports filed in the last 7 calendar days.",
    )
    reports_last_30_days: int = Field(
        ...,
        description="Number of reports filed in the last 30 calendar days.",
    )
    avg_resolution_hours: Optional[float] = Field(
        None,
        description=(
            "Average hours between filed_at and reviewed_at for resolved reports "
            "(REVIEWED, ESCALATED, CLOSED).  Null when no resolved reports exist."
        ),
    )
