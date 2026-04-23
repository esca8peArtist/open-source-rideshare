"""Pydantic schemas for the driver safety check-in timer feature.

POST   /drivers/me/check-in-timer          — start a timer
GET    /drivers/me/check-in-timer          — get current timer
POST   /drivers/me/check-in-timer/confirm  — confirm safe (dismiss timer)
DELETE /drivers/me/check-in-timer          — cancel timer without confirming
GET    /drivers/me/check-in-timer/history  — list past timers
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DriverCheckInTimerStatus(str, Enum):
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class StartDriverCheckInTimerRequest(BaseModel):
    """Request body for starting a driver check-in timer."""

    duration_minutes: int = Field(
        ...,
        ge=5,
        le=120,
        description="How long (in minutes) before emergency contacts are notified if no check-in. Must be between 5 and 120.",
    )
    notes: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional context note (e.g. 'passenger seems agitated').",
    )


class DriverCheckInTimerResponse(BaseModel):
    """Check-in timer record returned to the driver."""

    id: int = Field(..., description="Unique timer identifier.")
    driver_id: int
    duration_minutes: int
    status: DriverCheckInTimerStatus
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
