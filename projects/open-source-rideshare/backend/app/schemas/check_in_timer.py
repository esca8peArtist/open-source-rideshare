"""Pydantic schemas for the rider safety check-in timer feature.

POST   /riders/me/check-in-timer          — start a timer
GET    /riders/me/check-in-timer          — get current timer
POST   /riders/me/check-in-timer/confirm  — confirm safe (cancel timer)
DELETE /riders/me/check-in-timer          — cancel timer without confirming
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CheckInTimerStatus(str, Enum):
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class StartCheckInTimerRequest(BaseModel):
    """Request body for starting a check-in timer."""

    duration_minutes: int = Field(
        ...,
        ge=5,
        le=120,
        description="How long (in minutes) before trusted contacts are notified if no check-in. Must be between 5 and 120.",
    )
    notes: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional context note (e.g. 'taking a rideshare home').",
    )


class CheckInTimerResponse(BaseModel):
    """Check-in timer record returned to the rider."""

    id: int = Field(..., description="Unique timer identifier.")
    rider_id: int
    duration_minutes: int
    status: CheckInTimerStatus
    notes: Optional[str] = None
    started_at: datetime
    expires_at: datetime
    confirmed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    expired_notified_at: Optional[datetime] = None
    minutes_remaining: Optional[float] = Field(
        None,
        description="Minutes remaining until expiry. None if timer is not ACTIVE.",
    )
