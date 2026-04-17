"""Pydantic schemas for the driver welfare summary response.

These are pure response schemas — they are not backed by ORM models directly,
but assembled by the service layer from multiple queries.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class ShiftMetrics(BaseModel):
    """Hours-of-service metrics derived from this week's shifts."""

    hours_this_week: float
    hours_today: float
    max_consecutive_hours: Optional[float]
    active_shift_hours: Optional[float]
    fatigue_risk: str  # "low" | "moderate" | "high"
    recommended_weekly_max_hours: float
    recommended_daily_max_hours: float


class EarningsMetrics(BaseModel):
    """Earnings and goal-progress metrics for this week."""

    earnings_this_week_usd: float
    tips_this_week_usd: float
    rides_completed_this_week: int
    estimated_hourly_rate_usd: Optional[float]
    earnings_goal_set: bool
    earnings_goal_target_usd: Optional[float]
    earnings_goal_progress_pct: Optional[float]


class InsuranceStatus(BaseModel):
    """Summary of the driver's active insurance document status."""

    status: str  # "active" | "expiring_soon" | "expired" | "pending" | "not_on_file"
    expires_on: Optional[date]
    days_until_expiry: Optional[int]


class CooperativeStatus(BaseModel):
    """Driver's standing within the cooperative."""

    is_approved_member: bool
    total_trips_lifetime: int
    average_rating: float
    background_check_status: str


class SupportResource(BaseModel):
    """A welfare or support resource available to drivers."""

    name: str
    description: str


class DriverWelfareSummary(BaseModel):
    """Top-level welfare summary returned by GET /driver/me/welfare-summary."""

    as_of: datetime
    shift_metrics: ShiftMetrics
    earnings_metrics: EarningsMetrics
    insurance_status: InsuranceStatus
    cooperative_status: CooperativeStatus
    welfare_note: str
    support_resources: list[SupportResource]
