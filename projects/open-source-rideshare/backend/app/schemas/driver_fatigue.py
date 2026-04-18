"""Pydantic schemas for the driver fatigue monitoring feature.

GET  /drivers/me/fatigue-status              — driver sees own status
GET  /admin/driver-fatigue-alerts            — admin sees all WARNING/LIMIT_REACHED drivers
POST /admin/driver-fatigue/{driver_id}/reset — admin manually resets driver fatigue
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FatigueStatusLevel(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    LIMIT_REACHED = "LIMIT_REACHED"


class FatigueStatus(BaseModel):
    """Fatigue status returned to a driver for their own record."""

    driver_id: int = Field(..., description="Driver user ID.")
    status: FatigueStatusLevel = Field(
        ...,
        description=(
            "NORMAL (<8h active), WARNING (8–10h, can still accept rides), "
            "or LIMIT_REACHED (≥10h, blocked from new rides)."
        ),
    )
    active_hours_last_24h: float = Field(
        ...,
        description="Total active driving hours in the rolling 24-hour window, rounded to 1 decimal.",
    )
    rides_today: int = Field(
        ...,
        description="Number of ride events logged in the last 24 hours.",
    )
    rest_hours_needed: Optional[float] = Field(
        None,
        description=(
            "Hours of consecutive rest still needed before status resets. "
            "Non-null only when status is LIMIT_REACHED."
        ),
    )
    message: str = Field(..., description="Human-readable summary of current fatigue status.")


class FatigueAlert(BaseModel):
    """Fatigue alert summary used by admin endpoints."""

    driver_id: int = Field(..., description="Driver user ID.")
    driver_name: str = Field(..., description="Driver's display name.")
    status: FatigueStatusLevel
    active_hours_last_24h: float
    last_ride_ended_at: Optional[datetime] = Field(
        None,
        description="Timestamp of the most recent RIDE_ENDED event, if any.",
    )
