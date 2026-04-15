"""Pydantic schemas for driver shift / hours tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.driver_shift import ShiftStatus


# ---------------------------------------------------------------------------
# Fatigue policy constants (platform-configurable in production via env/config)
# ---------------------------------------------------------------------------

MAX_HOURS_PER_DAY: float = 12.0
MAX_HOURS_PER_WEEK: float = 60.0
BREAK_AFTER_HOURS: float = 4.0      # recommend a break after this many hours on shift
BREAK_DURATION_MINUTES: float = 30.0  # recommended break length


# ---------------------------------------------------------------------------
# Shift schemas
# ---------------------------------------------------------------------------

class DriverShiftOut(BaseModel):
    id: int
    driver_id: int
    started_at: datetime
    ended_at: Optional[datetime]
    status: ShiftStatus
    rides_completed: int
    total_minutes: Optional[float]
    admin_note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DriverShiftListOut(BaseModel):
    shifts: list[DriverShiftOut]
    total: int


# ---------------------------------------------------------------------------
# Hours summary schemas
# ---------------------------------------------------------------------------

class DailyHoursSummary(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    hours_worked: float
    shifts_count: int
    at_daily_limit: bool
    minutes_until_daily_limit: float  # 0 if already at/over limit


class HoursSummaryOut(BaseModel):
    driver_id: int
    today: DailyHoursSummary
    week_start: str = Field(..., description="YYYY-MM-DD (Monday of current week)")
    weekly_hours: float
    weekly_shifts: int
    at_weekly_limit: bool
    minutes_until_weekly_limit: float
    active_shift: Optional[DriverShiftOut]


# ---------------------------------------------------------------------------
# Fatigue / break recommendation schema
# ---------------------------------------------------------------------------

class FatigueStatusOut(BaseModel):
    driver_id: int
    has_active_shift: bool
    shift_minutes_elapsed: Optional[float] = Field(
        None, description="Minutes since current shift started"
    )
    break_recommended: bool = Field(
        False,
        description="True when driver has been on shift >= BREAK_AFTER_HOURS without a break",
    )
    minutes_until_break_due: Optional[float] = Field(
        None,
        description="Minutes remaining before a break is recommended (None if no active shift)",
    )
    daily_hours_remaining: Optional[float] = Field(
        None,
        description="Hours remaining within today's daily limit",
    )
    weekly_hours_remaining: Optional[float] = Field(
        None,
        description="Hours remaining within this week's limit",
    )
    max_hours_per_day: float = MAX_HOURS_PER_DAY
    max_hours_per_week: float = MAX_HOURS_PER_WEEK
    break_after_hours: float = BREAK_AFTER_HOURS


# ---------------------------------------------------------------------------
# Admin schemas
# ---------------------------------------------------------------------------

class AdminShiftRow(BaseModel):
    id: int
    driver_id: int
    driver_name: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    status: ShiftStatus
    rides_completed: int
    total_minutes: Optional[float]
    admin_note: Optional[str]

    model_config = {"from_attributes": True}


class AdminShiftListOut(BaseModel):
    shifts: list[AdminShiftRow]
    total: int


class AdminHoursSummaryOut(BaseModel):
    total_active_shifts: int
    drivers_near_daily_limit: int   # within 1 h of daily limit today
    drivers_near_weekly_limit: int  # within 5 h of weekly limit this week
    drivers_over_daily_limit: int
    drivers_over_weekly_limit: int
    average_shift_hours_today: float


class AdminForceEndShift(BaseModel):
    admin_note: Optional[str] = Field(None, max_length=500)
