"""Pydantic schemas for the Driver Mentorship Program."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.driver_mentorship import MentorshipStatus


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Mentorship request / assignment
# ---------------------------------------------------------------------------


class MentorshipRequestCreate(BaseModel):
    """Payload when a new driver requests mentorship assignment."""

    note: str | None = Field(
        default=None,
        max_length=500,
        description="Optional note to admin about the request",
    )


class AdminAssignMentorRequest(BaseModel):
    """Payload when an admin assigns a mentor to a pending mentorship."""

    mentor_id: int = Field(description="User ID of the driver to assign as mentor")
    commission_rate: float = Field(
        default=0.02,
        ge=0.0,
        le=0.2,
        description="Fraction of mentee ride earnings paid as commission (0–20%)",
    )
    commission_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Number of days the commission period lasts",
    )
    admin_note: str | None = Field(default=None, max_length=500)

    @field_validator("commission_rate")
    @classmethod
    def rate_precision(cls, v: float) -> float:
        return round(v, 4)


class AdminCancelMentorshipRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class MentorshipEarningResponse(_OrmBase):
    id: int
    mentorship_id: int
    ride_id: int
    mentee_earnings: float
    commission_amount: float
    created_at: datetime
    paid_at: datetime | None


class MentorshipResponse(_OrmBase):
    id: int
    mentee_id: int
    mentor_id: int | None
    status: MentorshipStatus
    commission_rate: float
    commission_days: int
    started_at: datetime | None
    ends_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    admin_note: str | None
    created_at: datetime
    updated_at: datetime


class MenteeListItem(_OrmBase):
    """Compact view of a mentee (for mentor's /me/mentees endpoint)."""

    id: int
    mentee_id: int
    status: MentorshipStatus
    started_at: datetime | None
    ends_at: datetime | None
    total_commission_earned: float = 0.0


class MentorEarningSummary(BaseModel):
    """Aggregated earnings summary for a mentor."""

    mentor_id: int
    active_mentee_count: int
    lifetime_commission_earned: float
    unpaid_commission: float


class AdminMentorshipSummary(BaseModel):
    """Platform-wide mentorship statistics for admin dashboard."""

    total_pending: int
    total_active: int
    total_completed: int
    total_cancelled: int
    total_commission_paid: float
    total_commission_unpaid: float
