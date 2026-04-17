"""Service layer for driver earnings history.

Returns a week-by-week breakdown of a driver's completed-ride earnings over a
configurable trailing window.  All weeks in the window are always included —
weeks with no rides appear as zeroed buckets — so callers get a consistent
time-series suitable for charting.

Approach
--------
A single DB query fetches the raw ride rows (requested_at, actual_fare,
tip_amount) for the window.  All grouping and aggregation runs in Python for
full testability without a live database.

Week boundaries
---------------
Weeks are ISO-style: Monday → Sunday (UTC).  The current partial week is
included as bucket 0 (newest); the oldest bucket is bucket N-1.  Output is
returned oldest-first so charts render left-to-right without re-sorting.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.driver_earnings_history import (
    DriverEarningsHistory,
    WeeklyEarningsBucket,
)

# --------------------------------------------------------------------------- #
# Public constants (imported by tests)
# --------------------------------------------------------------------------- #

HISTORY_WEEKS_DEFAULT: int = 12
HISTORY_WEEKS_MAX: int = 52

# Threshold for trend classification (±10 % relative change)
TREND_THRESHOLD: float = 0.10


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    """Return current UTC time.  Patched by tests for determinism."""
    return datetime.now(tz=timezone.utc)


def _week_start_for(d: date) -> date:
    """Return the Monday of the ISO week containing *d*."""
    return d - timedelta(days=d.weekday())


def _build_empty_buckets(now: datetime, weeks: int) -> list[WeeklyEarningsBucket]:
    """Generate *weeks* zeroed buckets from **oldest** to **newest**.

    Bucket 0 (index 0 in the returned list) is the oldest week; the last
    bucket is the current (possibly partial) week.
    """
    current_week_mon = _week_start_for(now.date())
    buckets: list[WeeklyEarningsBucket] = []
    for k in range(weeks - 1, -1, -1):  # weeks-1 down to 0 → oldest first
        ws = current_week_mon - timedelta(weeks=k)
        we = ws + timedelta(days=6)
        buckets.append(
            WeeklyEarningsBucket(
                week_start=ws,
                week_end=we,
                earnings_usd=0.0,
                ride_count=0,
                avg_fare_usd=None,
                tip_total_usd=0.0,
            )
        )
    return buckets


def _compute_trend(
    buckets: list[WeeklyEarningsBucket],
    weeks_requested: int,
) -> Literal["improving", "declining", "stable", "insufficient_data"]:
    """Classify the earnings trend across the history window.

    Uses a simple first-half vs second-half comparison:
    - ``insufficient_data`` when fewer than 4 weeks are requested.
    - Splits the bucket list in half (integer division); the second half is
      the more recent period.
    - If recent_avg ≥ older_avg * (1 + TREND_THRESHOLD) → ``improving``.
    - If recent_avg ≤ older_avg * (1 - TREND_THRESHOLD) → ``declining``.
    - Otherwise → ``stable``.
    - Edge: both halves are zero → ``stable``.
    """
    if weeks_requested < 4:
        return "insufficient_data"

    mid = len(buckets) // 2
    older = buckets[:mid]
    newer = buckets[mid:]

    older_avg = sum(b.earnings_usd for b in older) / len(older) if older else 0.0
    newer_avg = sum(b.earnings_usd for b in newer) / len(newer) if newer else 0.0

    if older_avg == 0.0 and newer_avg == 0.0:
        return "stable"
    if older_avg == 0.0:
        # Any earnings in the newer half after zero older half → improving
        return "improving"

    ratio = newer_avg / older_avg
    if ratio >= 1.0 + TREND_THRESHOLD:
        return "improving"
    if ratio <= 1.0 - TREND_THRESHOLD:
        return "declining"
    return "stable"


def _finalise_bucket(
    ws: date,
    we: date,
    earnings: float,
    ride_count: int,
    tips: float,
) -> WeeklyEarningsBucket:
    """Return a completed WeeklyEarningsBucket with avg_fare_usd computed."""
    avg_fare: Optional[float] = (
        round(earnings / ride_count, 2) if ride_count > 0 else None
    )
    return WeeklyEarningsBucket(
        week_start=ws,
        week_end=we,
        earnings_usd=round(earnings, 2),
        ride_count=ride_count,
        avg_fare_usd=avg_fare,
        tip_total_usd=round(tips, 2),
    )


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #


async def get_driver_earnings_history(
    db: AsyncSession,
    driver_id: int,
    weeks: int = HISTORY_WEEKS_DEFAULT,
) -> DriverEarningsHistory:
    """Build and return the earnings history for the given driver.

    Fetches all completed rides in the trailing *weeks*-week window, groups
    them into weekly buckets in Python, and computes totals and trend.

    Parameters
    ----------
    db:
        Async SQLAlchemy session.
    driver_id:
        ID of the authenticated driver.
    weeks:
        Number of trailing weeks to include (1–52).
    """
    now = _utc_now()
    current_week_mon = _week_start_for(now.date())
    oldest_week_mon = current_week_mon - timedelta(weeks=weeks - 1)
    window_start_dt = datetime.combine(oldest_week_mon, time.min, tzinfo=timezone.utc)

    # Fetch all completed rides in the window for this driver
    result = await db.execute(
        select(Ride.requested_at, Ride.actual_fare, Ride.tip_amount).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.requested_at >= window_start_dt,
        )
    )
    rows = result.all()

    # Build mutable accumulator keyed on week_start date
    # Preserves insertion order (oldest → newest) — Python 3.7+ dict
    template_buckets = _build_empty_buckets(now, weeks)
    accum: dict[date, dict] = {
        b.week_start: {
            "week_end": b.week_end,
            "earnings": 0.0,
            "rides": 0,
            "tips": 0.0,
        }
        for b in template_buckets
    }

    for row in rows:
        # Normalise to a UTC-aware datetime regardless of DB storage
        req_at: datetime = row.requested_at
        if req_at.tzinfo is None:
            req_at = req_at.replace(tzinfo=timezone.utc)
        ride_week_mon = _week_start_for(req_at.date())

        entry = accum.get(ride_week_mon)
        if entry is None:
            continue  # outside the requested window (should not happen)

        fare = float(row.actual_fare or 0.0)
        tip = float(row.tip_amount or 0.0)
        entry["earnings"] += fare
        entry["rides"] += 1
        entry["tips"] += tip

    # Build final bucket list (oldest-first order preserved)
    final_buckets: list[WeeklyEarningsBucket] = [
        _finalise_bucket(ws, entry["week_end"], entry["earnings"], entry["rides"], entry["tips"])
        for ws, entry in accum.items()
    ]

    total_earnings = round(sum(b.earnings_usd for b in final_buckets), 2)
    total_rides = sum(b.ride_count for b in final_buckets)
    avg_weekly = round(total_earnings / weeks, 2)

    best_week: Optional[WeeklyEarningsBucket] = (
        max(final_buckets, key=lambda b: b.earnings_usd)
        if total_earnings > 0.0
        else None
    )

    trend = _compute_trend(final_buckets, weeks)

    return DriverEarningsHistory(
        as_of=now,
        weeks_requested=weeks,
        weeks=final_buckets,
        total_earnings_usd=total_earnings,
        total_rides=total_rides,
        avg_weekly_earnings_usd=avg_weekly,
        best_week=best_week,
        trend=trend,
    )
