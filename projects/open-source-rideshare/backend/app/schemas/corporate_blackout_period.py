"""Pydantic v2 schemas for the Corporate Blackout Periods feature.

Admins define named date ranges (one-time or recurring) during which corporate
bookings are restricted.  The check endpoint lets callers ask whether a
proposed booking datetime is covered by any active blackout window.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class BlackoutPeriodCreate(BaseModel):
    """Payload for creating a new blackout period."""

    name: str = Field(..., min_length=1, max_length=200, description="Admin-friendly name.")
    start_datetime: datetime = Field(..., description="Inclusive start of the blackout window (UTC).")
    end_datetime: datetime = Field(..., description="Inclusive end of the blackout window (UTC).")
    recurrence: str = Field(
        "none",
        description="Repeat pattern: 'none' (one-time), 'annual', or 'weekly'.",
    )
    affected_days: Optional[list[int]] = Field(
        None,
        description=(
            "For weekly recurrence: weekday integers to block (0=Mon … 6=Sun). "
            "The time-of-day window comes from start/end_datetime times."
        ),
    )
    override_allowed: bool = Field(
        False,
        description="Whether employees may request an override booking.",
    )
    override_requires_approval: bool = Field(
        True,
        description="When True, overrides must go through the ride-approval workflow.",
    )
    reason: Optional[str] = Field(None, description="Human-readable reason for the restriction.")

    @model_validator(mode="after")
    def end_after_start(self) -> "BlackoutPeriodCreate":
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime.")
        return self


class BlackoutPeriodUpdate(BaseModel):
    """Partial update — all fields optional."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    recurrence: Optional[str] = None
    affected_days: Optional[list[int]] = None
    override_allowed: Optional[bool] = None
    override_requires_approval: Optional[bool] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def end_after_start_if_both(self) -> "BlackoutPeriodUpdate":
        if self.start_datetime is not None and self.end_datetime is not None:
            if self.end_datetime <= self.start_datetime:
                raise ValueError("end_datetime must be after start_datetime.")
        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class BlackoutPeriodResponse(BaseModel):
    """Full representation of a single blackout period."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    corporate_account_id: int
    name: str
    start_datetime: datetime
    end_datetime: datetime
    recurrence: str
    affected_days: Optional[list[int]]
    override_allowed: bool
    override_requires_approval: bool
    reason: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class BlackoutPeriodListResponse(BaseModel):
    """Paginated list of blackout periods."""

    items: list[BlackoutPeriodResponse]
    total: int


class BlackoutCheckResponse(BaseModel):
    """Result of the check-booking endpoint."""

    dt: datetime
    is_blacked_out: bool
    active_periods: list[BlackoutPeriodResponse]
