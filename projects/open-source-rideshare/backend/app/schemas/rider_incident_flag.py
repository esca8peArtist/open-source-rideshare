"""Pydantic schemas for rider incident flags.

A rider incident flag is automatically raised when a rider accumulates
INCIDENT_THRESHOLD driver safety reports within INCIDENT_WINDOW_DAYS days.
Flags route to admin review and can suppress the rider from further matching
while under investigation.

Admin endpoints:
    GET    /admin/rider-incident-flags                    — list all flags
    GET    /admin/rider-incident-flags/{rider_id}         — get flag for rider
    POST   /admin/rider-incident-flags/{rider_id}/review  — review flag
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

INCIDENT_THRESHOLD = 3
INCIDENT_WINDOW_DAYS = 90


class FlagStatus(str, Enum):
    ACTIVE = "active"
    UNDER_REVIEW = "under_review"
    CLEARED = "cleared"


class RiderIncidentFlagResponse(BaseModel):
    """A rider incident flag record returned to admins."""

    rider_id: int = Field(..., description="ID of the flagged rider.")
    report_count: int = Field(
        ...,
        description=(
            "Number of driver safety reports against this rider within the "
            f"rolling {INCIDENT_WINDOW_DAYS}-day window at time of last flag raise."
        ),
    )
    status: FlagStatus = Field(..., description="Current flag status.")
    flagged_at: datetime = Field(..., description="UTC timestamp when flag was first raised.")
    last_updated_at: datetime = Field(..., description="UTC timestamp of most recent status change.")
    reviewed_by: Optional[int] = Field(None, description="Admin user ID who last reviewed.")
    admin_notes: Optional[str] = Field(None, description="Admin notes on the review outcome.")

    model_config = {"from_attributes": True}


class RiderIncidentFlagListResponse(BaseModel):
    """Paginated list of rider incident flags."""

    total: int = Field(..., description="Total matching flags (before pagination).")
    items: list[RiderIncidentFlagResponse]


class AdminReviewIncidentFlagRequest(BaseModel):
    """Admin request body for reviewing a rider incident flag."""

    review_status: FlagStatus = Field(
        ...,
        description=(
            "New flag status. Must be 'under_review' or 'cleared'. "
            "Cannot set to 'active' — flags become active automatically."
        ),
    )
    admin_notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Admin notes on the review outcome.",
    )
