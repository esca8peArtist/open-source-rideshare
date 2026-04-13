"""Pydantic v2 schemas for driver incentive / bonus programs."""
from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class IncentiveProgramCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field(default="", max_length=1000)
    program_type: str = Field(..., description="quest | peak_hours | streak | earnings_guarantee")
    bonus_amount: float = Field(..., gt=0)
    trip_target: int | None = Field(default=None, gt=0)
    start_time: time | None = None
    end_time: time | None = None
    start_date: date
    end_date: date | None = None
    days_of_week: str | None = Field(
        default=None,
        description="Comma-separated day-of-week ints: '0,1,2,3,4' (Mon=0). None = all days.",
    )
    is_active: bool = True


class IncentiveProgramUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    program_type: str | None = None
    bonus_amount: float | None = Field(default=None, gt=0)
    trip_target: int | None = Field(default=None, gt=0)
    start_time: time | None = None
    end_time: time | None = None
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: str | None = None
    is_active: bool | None = None


class IncentiveProgramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    program_type: str
    bonus_amount: float
    trip_target: int | None
    start_time: time | None
    end_time: time | None
    start_date: date
    end_date: date | None
    days_of_week: str | None
    is_active: bool
    created_at: datetime


class DriverProgressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    driver_id: int
    program_id: int
    trips_completed: int
    bonus_earned: float
    status: str
    period_start: date
    completed_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DriverIncentiveSummary(BaseModel):
    """A driver's view of one active program, including their current progress."""

    program: IncentiveProgramResponse
    progress: DriverProgressResponse | None
    trips_remaining: int | None  # Meaningful for quest/streak; None for peak_hours/earnings_guarantee
    potential_bonus: float


class IncentiveEligibilityResponse(BaseModel):
    eligible: bool
    reason: str | None = None
