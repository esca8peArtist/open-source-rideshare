"""Pydantic schemas for the driver earnings comparison response.

Compares a single driver's trailing average weekly earnings against the
platform-wide average across all active drivers in the same period.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EarningsPercentile(BaseModel):
    """Rank and percentile of the driver within all active drivers."""

    rank: int  # 1-based; 1 = highest earner on the platform
    total_drivers: int  # active drivers with ≥1 completed ride in the period
    percentile: float  # 0.0–100.0; higher = more drivers earn less than you


class DriverEarningsComparison(BaseModel):
    """Full earnings comparison returned by GET /driver/me/earnings-comparison."""

    as_of: datetime
    period_weeks: int  # trailing window used for the analysis
    driver_avg_weekly_usd: float  # this driver's trailing avg weekly earnings
    platform_avg_weekly_usd: float  # mean across all active drivers
    difference_usd: float  # driver_avg - platform_avg (positive = above average)
    difference_pct: Optional[float]  # None if platform_avg is 0; else % difference
    percentile: EarningsPercentile
    active_drivers_in_period: int  # total drivers with ≥1 completed ride
    comparison_note: str  # human-readable summary
