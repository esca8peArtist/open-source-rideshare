"""Service layer for rider spending summary.

Returns a snapshot of a rider's spending across four time windows:
today, this week (ISO Mon–now), this month (1st–now), and lifetime.
Also computes total tips given, total promo savings, and the most
frequently travelled route across all lifetime completed rides.

Approach
--------
A single DB query fetches all completed rides.  All bucketing and
arithmetic runs in Python for full testability without a live database.

Period boundaries (all UTC)
---------------------------
today      — calendar day start (00:00:00) to now
this_week  — Monday 00:00:00 of current ISO week to now
this_month — 1st of current month 00:00:00 to now
lifetime   — all completed rides ever
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.rider_spending_summary import (
    FrequentRoute,
    RiderSpendingSummary,
    SpendingPeriod,
)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    """Return current UTC time.  Patched by tests for determinism."""
    return datetime.now(tz=timezone.utc)


def _compute_period(fares: list[float]) -> SpendingPeriod:
    """Compute aggregated spending for a list of actual_fare values.

    Args:
        fares: Each element is the actual_fare for one completed ride.

    Returns:
        A SpendingPeriod with monetary values rounded to 2 decimal places.
    """
    if not fares:
        return SpendingPeriod(trip_count=0, total_spent=0.0, avg_fare=0.0)

    total = round(sum(fares), 2)
    avg = round(total / len(fares), 2)

    return SpendingPeriod(
        trip_count=len(fares),
        total_spent=total,
        avg_fare=avg,
    )


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #


async def get_rider_spending_summary(
    db: AsyncSession,
    rider_id: int,
) -> RiderSpendingSummary:
    """Build and return the spending summary for the given rider.

    Queries all completed rides for the rider, buckets them into time
    windows in Python, and computes tip totals, promo savings, and the
    most frequent route.

    Args:
        db: Async SQLAlchemy session.
        rider_id: ID of the authenticated rider.
    """
    now = _utc_now()

    # Time window boundaries (UTC)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    days_since_monday = now.weekday()  # 0=Monday
    week_start_date = now.date() - timedelta(days=days_since_monday)
    week_start = datetime.combine(week_start_date, time.min, tzinfo=timezone.utc)

    month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=timezone.utc)

    # Fetch all completed rides for this rider (lifetime)
    result = await db.execute(
        select(
            Ride.actual_fare,
            Ride.tip_amount,
            Ride.promo_discount,
            Ride.pickup_address,
            Ride.dropoff_address,
            Ride.completed_at,
        ).where(
            Ride.rider_id == rider_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.actual_fare.is_not(None),
        )
    )
    rows = result.all()

    # Bucket fares by time window; accumulate lifetime stats
    today_fares: list[float] = []
    week_fares: list[float] = []
    month_fares: list[float] = []
    lifetime_fares: list[float] = []

    total_tips = 0.0
    total_promo = 0.0
    route_counter: Counter[tuple[str, str]] = Counter()

    for row in rows:
        fare = float(row.actual_fare or 0.0)
        tip = float(row.tip_amount or 0.0)
        promo = float(row.promo_discount or 0.0)
        pickup = row.pickup_address or ""
        dropoff = row.dropoff_address or ""

        completed = row.completed_at
        if completed is not None and completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)

        lifetime_fares.append(fare)
        total_tips += tip
        total_promo += promo
        route_counter[(pickup, dropoff)] += 1

        if completed is not None:
            if completed >= month_start:
                month_fares.append(fare)
            if completed >= week_start:
                week_fares.append(fare)
            if completed >= today_start:
                today_fares.append(fare)

    # Most frequent route
    most_frequent_route: Optional[FrequentRoute] = None
    if route_counter:
        (top_pickup, top_dropoff), top_count = route_counter.most_common(1)[0]
        most_frequent_route = FrequentRoute(
            pickup=top_pickup,
            dropoff=top_dropoff,
            count=top_count,
        )

    return RiderSpendingSummary(
        rider_id=rider_id,
        as_of=now,
        today=_compute_period(today_fares),
        this_week=_compute_period(week_fares),
        this_month=_compute_period(month_fares),
        lifetime=_compute_period(lifetime_fares),
        total_tips_given=round(total_tips, 2),
        total_promo_savings=round(total_promo, 2),
        most_frequent_route=most_frequent_route,
    )
