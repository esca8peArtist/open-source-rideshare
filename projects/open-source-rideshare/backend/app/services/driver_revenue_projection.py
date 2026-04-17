"""Service layer for driver revenue projections.

Analyses the driver's completed ride history over the last 8 weeks and
produces a forward-looking revenue projection, including:
  - Trailing average weekly earnings and projected monthly earnings
  - Trend classification (improving / stable / declining)
  - Best earning hours and days of the week
  - Full hourly and daily breakdowns
  - Per-week history
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.driver_revenue_projection import (
    DailyBreakdown,
    DriverRevenueProjection,
    HourlyBreakdown,
    WeeklyEarnings,
)

# --------------------------------------------------------------------------- #
# Public constants (imported by tests)
# --------------------------------------------------------------------------- #

ANALYSIS_WEEKS: int = 8
TREND_WEEKS: int = 4  # Split analysis window into two halves for trend
WEEKS_PER_MONTH: float = 52.0 / 12.0  # ≈ 4.33

_DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    """Return the current UTC time. Patched by tests for determinism."""
    return datetime.now(tz=timezone.utc)


def _iso_week_start(dt: datetime) -> date:
    """Return the Monday of the ISO week containing *dt*."""
    d = dt.date()
    return d - timedelta(days=d.weekday())


def _build_weekly_history(
    rides: list,
    window_start: datetime,
    now: datetime,
) -> list[WeeklyEarnings]:
    """Aggregate rides into per-ISO-week buckets, oldest first."""
    buckets: dict[date, dict] = {}

    for ride in rides:
        if ride.requested_at < window_start:
            continue
        ws = _iso_week_start(ride.requested_at)
        if ws not in buckets:
            buckets[ws] = {"earnings": 0.0, "rides": 0, "tips": 0.0}
        fare = ride.actual_fare or 0.0
        buckets[ws]["earnings"] += fare
        buckets[ws]["rides"] += 1
        buckets[ws]["tips"] += ride.tip_amount or 0.0

    return [
        WeeklyEarnings(
            week_start=ws,
            earnings_usd=round(v["earnings"], 2),
            rides=v["rides"],
            tips_usd=round(v["tips"], 2),
        )
        for ws, v in sorted(buckets.items())
    ]


def _classify_trend(weekly_history: list[WeeklyEarnings]) -> str:
    """Classify earnings trend from the weekly history.

    Compares the mean of the *later* half of the window against the *earlier*
    half.  Requires at least TREND_WEEKS weeks on each side.

    Returns one of: "improving", "stable", "declining", "insufficient_data".
    """
    if len(weekly_history) < TREND_WEEKS:
        return "insufficient_data"

    mid = len(weekly_history) // 2
    earlier = weekly_history[:mid]
    later = weekly_history[mid:]

    avg_earlier = sum(w.earnings_usd for w in earlier) / len(earlier)
    avg_later = sum(w.earnings_usd for w in later) / len(later)

    if avg_earlier == 0:
        return "insufficient_data"

    change = (avg_later - avg_earlier) / avg_earlier
    if change > 0.10:
        return "improving"
    if change < -0.10:
        return "declining"
    return "stable"


def _build_hourly_breakdown(rides: list, num_weeks: int) -> list[HourlyBreakdown]:
    """Build a 24-entry hourly breakdown (avg per week with data)."""
    buckets: dict[int, dict] = {h: {"earnings": 0.0, "rides": 0, "tips": 0.0} for h in range(24)}

    for ride in rides:
        hour = ride.requested_at.hour
        buckets[hour]["earnings"] += ride.actual_fare or 0.0
        buckets[hour]["rides"] += 1
        buckets[hour]["tips"] += ride.tip_amount or 0.0

    divisor = max(num_weeks, 1)
    return [
        HourlyBreakdown(
            hour=h,
            avg_earnings_usd=round(v["earnings"] / divisor, 2),
            avg_rides=round(v["rides"] / divisor, 2),
            avg_tips_usd=round(v["tips"] / divisor, 2),
        )
        for h, v in sorted(buckets.items())
    ]


def _build_daily_breakdown(rides: list, num_weeks: int) -> list[DailyBreakdown]:
    """Build a 7-entry daily breakdown (avg per week with data)."""
    buckets: dict[int, dict] = {d: {"earnings": 0.0, "rides": 0} for d in range(7)}

    for ride in rides:
        dow = ride.requested_at.weekday()  # 0=Monday
        buckets[dow]["earnings"] += ride.actual_fare or 0.0
        buckets[dow]["rides"] += 1

    divisor = max(num_weeks, 1)
    return [
        DailyBreakdown(
            day_of_week=d,
            day_name=_DAY_NAMES[d],
            avg_earnings_usd=round(v["earnings"] / divisor, 2),
            avg_rides=round(v["rides"] / divisor, 2),
        )
        for d, v in sorted(buckets.items())
    ]


def _best_earning_hours(hourly: list[HourlyBreakdown], top_n: int = 3) -> list[int]:
    """Return the top-N hours sorted by avg_earnings_usd, descending."""
    ranked = sorted(hourly, key=lambda h: h.avg_earnings_usd, reverse=True)
    return [h.hour for h in ranked[:top_n]]


def _best_earning_days(daily: list[DailyBreakdown], top_n: int = 2) -> list[str]:
    """Return the top-N day names sorted by avg_earnings_usd, descending."""
    ranked = sorted(daily, key=lambda d: d.avg_earnings_usd, reverse=True)
    return [d.day_name for d in ranked[:top_n]]


def _build_projection_note(
    weeks_of_data: int,
    trend: str,
    avg_weekly: float,
    projected_monthly: float,
) -> str:
    """Generate a human-readable projection note."""
    if weeks_of_data == 0:
        return (
            "No completed ride history found. Complete your first rides to unlock "
            "personalised revenue projections."
        )

    trend_phrase = {
        "improving": "Your earnings are trending upward",
        "declining": "Your earnings have been declining recently",
        "stable": "Your earnings have been stable",
        "insufficient_data": "Based on limited data",
    }[trend]

    return (
        f"{trend_phrase}. Based on your last {weeks_of_data} week(s) of data, "
        f"you are averaging ${avg_weekly:.2f}/week and are on track to earn "
        f"approximately ${projected_monthly:.2f} this month."
    )


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #


async def get_driver_revenue_projection(
    db: AsyncSession,
    driver_id: int,
) -> DriverRevenueProjection:
    """Build and return a revenue projection for the given driver.

    Executes a single DB query: completed rides in the last ANALYSIS_WEEKS weeks.
    All aggregation is performed in Python for testability.
    """
    now = _utc_now()
    window_start = now - timedelta(weeks=ANALYSIS_WEEKS)

    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.requested_at >= window_start,
        )
    )
    rides = result.scalars().all()

    # --- Weekly history ---
    weekly_history = _build_weekly_history(rides, window_start, now)
    weeks_of_data = len(weekly_history)

    # --- Trailing average (last TREND_WEEKS or all available) ---
    trailing = weekly_history[-TREND_WEEKS:] if len(weekly_history) >= TREND_WEEKS else weekly_history
    if trailing:
        avg_weekly = sum(w.earnings_usd for w in trailing) / len(trailing)
    else:
        avg_weekly = 0.0
    projected_monthly = round(avg_weekly * WEEKS_PER_MONTH, 2)
    avg_weekly = round(avg_weekly, 2)

    # --- Trend ---
    trend = _classify_trend(weekly_history)

    # --- Breakdowns ---
    num_weeks = max(weeks_of_data, 1)
    hourly_breakdown = _build_hourly_breakdown(rides, num_weeks)
    daily_breakdown = _build_daily_breakdown(rides, num_weeks)

    best_hours = _best_earning_hours(hourly_breakdown)
    best_days = _best_earning_days(daily_breakdown)

    projection_note = _build_projection_note(weeks_of_data, trend, avg_weekly, projected_monthly)

    return DriverRevenueProjection(
        as_of=now,
        weeks_of_data=weeks_of_data,
        avg_weekly_earnings_usd=avg_weekly,
        projected_monthly_earnings_usd=projected_monthly,
        trend=trend,
        best_earning_hours=best_hours,
        best_earning_days=best_days,
        hourly_breakdown=hourly_breakdown,
        daily_breakdown=daily_breakdown,
        weekly_history=weekly_history,
        projection_note=projection_note,
    )
