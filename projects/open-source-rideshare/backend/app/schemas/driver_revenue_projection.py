"""Pydantic schemas for the driver revenue projection response.

Pure response schemas assembled by the service layer from historical ride data.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class HourlyBreakdown(BaseModel):
    """Earnings aggregated by hour of day across the analysis window."""

    hour: int  # 0–23
    avg_earnings_usd: float
    avg_rides: float
    avg_tips_usd: float


class DailyBreakdown(BaseModel):
    """Earnings aggregated by day of week across the analysis window."""

    day_of_week: int  # 0=Monday … 6=Sunday
    day_name: str
    avg_earnings_usd: float
    avg_rides: float


class WeeklyEarnings(BaseModel):
    """Actual earnings for a single ISO calendar week."""

    week_start: date  # Monday of the week (ISO)
    earnings_usd: float
    rides: int
    tips_usd: float


class DriverRevenueProjection(BaseModel):
    """Full revenue projection returned by GET /driver/me/revenue-projection."""

    as_of: datetime
    weeks_of_data: int
    avg_weekly_earnings_usd: float
    projected_monthly_earnings_usd: float
    trend: str  # "improving" | "stable" | "declining" | "insufficient_data"
    best_earning_hours: list[int]  # top-3 hours by avg earnings
    best_earning_days: list[str]  # top-2 day names by avg earnings
    hourly_breakdown: list[HourlyBreakdown]
    daily_breakdown: list[DailyBreakdown]
    weekly_history: list[WeeklyEarnings]
    projection_note: str
