"""Pydantic schemas for the driver earnings history response.

Provides a week-by-week breakdown of a driver's completed-ride earnings,
tips, and ride counts over a configurable trailing window (default 12 weeks,
max 52 weeks).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class WeeklyEarningsBucket(BaseModel):
    """Earnings summary for a single ISO calendar week (Mon–Sun)."""

    week_start: date  # Monday of this week
    week_end: date  # Sunday of this week
    earnings_usd: float  # sum of actual_fare for completed rides
    ride_count: int  # number of completed rides
    avg_fare_usd: Optional[float]  # earnings_usd / ride_count; None if ride_count == 0
    tip_total_usd: float  # sum of tip_amount for completed rides


class DriverEarningsHistory(BaseModel):
    """Full earnings history returned by GET /driver/me/earnings-history."""

    as_of: datetime
    weeks_requested: int  # trailing window size (1–52)
    weeks: list[WeeklyEarningsBucket]  # oldest-first; len == weeks_requested
    total_earnings_usd: float  # sum of earnings_usd across all buckets
    total_rides: int  # sum of ride_count across all buckets
    avg_weekly_earnings_usd: float  # total_earnings_usd / weeks_requested
    best_week: Optional[WeeklyEarningsBucket]  # highest-earnings bucket; None if all zero
    trend: Literal["improving", "declining", "stable", "insufficient_data"]
    # "improving"          — recent half of window earns ≥10% more than older half
    # "declining"          — recent half earns ≥10% less
    # "stable"             — within ±10%
    # "insufficient_data"  — weeks_requested < 4
