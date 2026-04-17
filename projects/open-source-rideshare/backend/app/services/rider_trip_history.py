"""Service layer for rider trip history.

GET /riders/me/trip-history
  Returns a paginated, filtered list of past trips for the authenticated rider.

Design decisions
----------------
Two DB queries are used:
  1. A COUNT query to get the total number of matching trips (for pagination).
  2. A paginated SELECT query to fetch the actual trip rows.

This keeps each query focused, avoids loading all rows just to count them, and
makes both paths independently testable.

All Python-side transformations (mapping Ride → TripSummary, computing fare)
are pure functions for full testability without a live database.

Filter semantics
----------------
status:
  "all"       — no status filter applied
  "completed" — only RideStatus.COMPLETED
  "cancelled" — only RideStatus.CANCELLED

from_date / to_date:
  Applied to Ride.requested_at (UTC).  from_date is midnight-inclusive at the
  start of the day; to_date is midnight-exclusive at the start of the NEXT day
  (i.e. the full to_date day is included).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.rider_trip_history import (
    RiderTripHistory,
    TripHistoryFilters,
    TripSummary,
)

# --------------------------------------------------------------------------- #
# Public constants
# --------------------------------------------------------------------------- #

DEFAULT_LIMIT: int = 20
MAX_LIMIT: int = 100


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _date_to_utc_start(d: date) -> datetime:
    """Convert a calendar date to midnight UTC at the start of that day."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _build_where_clauses(
    rider_id: int,
    status: Literal["all", "completed", "cancelled"],
    from_date: Optional[date],
    to_date: Optional[date],
) -> list:
    """Build SQLAlchemy WHERE clauses from filter parameters."""
    clauses = [Ride.rider_id == rider_id]

    if status == "completed":
        clauses.append(Ride.status == RideStatus.COMPLETED)
    elif status == "cancelled":
        clauses.append(Ride.status == RideStatus.CANCELLED)
    # "all" → no status filter

    if from_date is not None:
        clauses.append(Ride.requested_at >= _date_to_utc_start(from_date))

    if to_date is not None:
        # Include the full to_date day by using the start of the next day
        day_after = _date_to_utc_start(to_date) + timedelta(days=1)
        clauses.append(Ride.requested_at < day_after)

    return clauses


def _ride_to_summary(ride: Ride) -> TripSummary:
    """Map a Ride ORM instance to a TripSummary schema.

    fare_usd uses actual_fare when available (completed rides), falling back to
    estimated_fare for cancelled or in-progress rides.

    driver_rating maps to Ride.rider_rating — the rating the rider submitted for
    the driver (the model field name reflects which party submitted it).
    """
    fare = ride.actual_fare if ride.actual_fare is not None else ride.estimated_fare
    return TripSummary(
        ride_id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        requested_at=ride.requested_at,
        completed_at=ride.completed_at,
        cancelled_at=ride.cancelled_at,
        fare_usd=fare,
        distance_km=ride.distance_km,
        duration_min=ride.duration_min,
        tip_amount=ride.tip_amount,
        promo_discount=ride.promo_discount,
        driver_rating=ride.rider_rating,
        is_pool=ride.is_pool,
        cancellation_reason=ride.cancellation_reason,
    )


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #


async def get_rider_trip_history(
    db: AsyncSession,
    rider_id: int,
    status: Literal["all", "completed", "cancelled"],
    from_date: Optional[date],
    to_date: Optional[date],
    limit: int,
    offset: int,
) -> RiderTripHistory:
    """Fetch paginated trip history for the given rider.

    Executes two DB queries: one scalar COUNT for the total, one paginated
    SELECT for the actual rows.  Results are ordered newest-first.
    """
    where = _build_where_clauses(rider_id, status, from_date, to_date)

    # 1. Total count (pre-pagination)
    count_result = await db.execute(
        select(func.count()).select_from(Ride).where(*where)
    )
    total_count: int = count_result.scalar_one()

    # 2. Paginated rows, newest first
    rows_result = await db.execute(
        select(Ride)
        .where(*where)
        .order_by(Ride.requested_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rides = rows_result.scalars().all()

    trips = [_ride_to_summary(r) for r in rides]

    filters_applied = TripHistoryFilters(
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )

    return RiderTripHistory(
        total_count=total_count,
        trips=trips,
        filters_applied=filters_applied,
    )
