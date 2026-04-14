"""Scheduled ride service.

Handles creation, retrieval, cancellation, and driver accept/decline logic for
advance ride bookings.

Pure helpers (validate_scheduled_for, status checks) contain no I/O and are
fully unit-testable.  Async functions handle DB operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduled_ride import CancelledBy, ScheduledRide, ScheduledRideStatus

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

#: Riders must book at least this many minutes in advance.
MIN_ADVANCE_MINUTES: int = 30

#: Riders may not book more than this many days in the future.
MAX_ADVANCE_DAYS: int = 30

#: Default page size for list endpoints.
DEFAULT_PAGE_SIZE: int = 20


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, easy to unit test
# ---------------------------------------------------------------------------


def validate_scheduled_for(
    scheduled_for: datetime,
    now: datetime | None = None,
) -> str | None:
    """Validate the requested pickup time.

    Returns an error message string if invalid, or ``None`` if the time is
    acceptable.

    Args:
        scheduled_for: The requested pickup time (should be UTC-aware).
        now: Override for "now" (useful in tests).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Normalise timezone
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    min_time = now + timedelta(minutes=MIN_ADVANCE_MINUTES)
    max_time = now + timedelta(days=MAX_ADVANCE_DAYS)

    if scheduled_for < min_time:
        return (
            f"Scheduled time must be at least {MIN_ADVANCE_MINUTES} minutes in the future."
        )
    if scheduled_for > max_time:
        return f"Scheduled time must be within {MAX_ADVANCE_DAYS} days from now."
    return None


def is_cancellable(ride: ScheduledRide) -> bool:
    """Return True if the ride can still be cancelled."""
    return ride.status in (
        ScheduledRideStatus.PENDING,
        ScheduledRideStatus.DRIVER_ASSIGNED,
    )


def is_acceptable_by_driver(ride: ScheduledRide, driver_id: int) -> tuple[bool, str]:
    """Check whether a driver can accept this booking.

    Returns:
        (ok, error_message) — ok is True when the driver may accept.
    """
    if ride.status != ScheduledRideStatus.PENDING:
        return False, "This booking is no longer available for acceptance."
    if ride.driver_id == driver_id:
        return False, "You have already accepted this booking."
    return True, ""


def is_declinable_by_driver(ride: ScheduledRide, driver_id: int) -> tuple[bool, str]:
    """Check whether a driver can decline this booking.

    Only the assigned driver can decline, and only while status is
    ``driver_assigned``.
    """
    if ride.status != ScheduledRideStatus.DRIVER_ASSIGNED:
        return False, "Only driver-assigned bookings can be declined."
    if ride.driver_id != driver_id:
        return False, "You are not the assigned driver for this booking."
    return True, ""


# ---------------------------------------------------------------------------
# Async DB operations
# ---------------------------------------------------------------------------


async def create_scheduled_ride(
    db: AsyncSession,
    *,
    rider_id: int,
    pickup_lat: float,
    pickup_lon: float,
    pickup_address: str,
    dropoff_lat: float,
    dropoff_lon: float,
    dropoff_address: str,
    scheduled_for: datetime,
    estimated_fare: float | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> tuple[ScheduledRide | None, str | None]:
    """Create a new scheduled ride booking.

    Returns:
        (ride, None)            on success.
        (None, error_message)   if validation fails.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    err = validate_scheduled_for(scheduled_for, now)
    if err:
        return None, err

    ride = ScheduledRide(
        rider_id=rider_id,
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        pickup_address=pickup_address,
        dropoff_lat=dropoff_lat,
        dropoff_lon=dropoff_lon,
        dropoff_address=dropoff_address,
        scheduled_for=scheduled_for,
        estimated_fare=estimated_fare,
        notes=notes,
        status=ScheduledRideStatus.PENDING,
    )
    db.add(ride)
    await db.commit()
    await db.refresh(ride)
    return ride, None


async def get_scheduled_ride(
    db: AsyncSession, ride_id: int
) -> ScheduledRide | None:
    """Fetch a single scheduled ride by ID."""
    result = await db.execute(
        select(ScheduledRide).where(ScheduledRide.id == ride_id)
    )
    return result.scalar_one_or_none()


async def list_rider_scheduled_rides(
    db: AsyncSession,
    rider_id: int,
    *,
    status: ScheduledRideStatus | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[Sequence[ScheduledRide], int]:
    """List scheduled rides for a rider with optional status filter.

    Returns:
        (items, total_count)
    """
    q = select(ScheduledRide).where(ScheduledRide.rider_id == rider_id)
    if status is not None:
        q = q.where(ScheduledRide.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    q = q.order_by(ScheduledRide.scheduled_for.asc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def list_driver_scheduled_rides(
    db: AsyncSession,
    driver_id: int,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[Sequence[ScheduledRide], int]:
    """List scheduled rides assigned to a driver (driver_assigned or in_progress).

    Also includes pending rides so drivers can voluntarily accept bookings.

    Returns:
        (items, total_count)
    """
    q = select(ScheduledRide).where(
        (ScheduledRide.driver_id == driver_id)
        | (ScheduledRide.status == ScheduledRideStatus.PENDING)
    )

    count_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    q = q.order_by(ScheduledRide.scheduled_for.asc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def driver_accept_scheduled_ride(
    db: AsyncSession,
    ride_id: int,
    driver_id: int,
    now: datetime | None = None,
) -> tuple[ScheduledRide | None, str | None]:
    """Driver accepts a pending scheduled ride booking.

    Returns:
        (ride, None)          on success.
        (None, error_message) if the ride cannot be accepted.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    ride = await get_scheduled_ride(db, ride_id)
    if ride is None:
        return None, "Scheduled ride not found."

    ok, err = is_acceptable_by_driver(ride, driver_id)
    if not ok:
        return None, err

    ride.driver_id = driver_id
    ride.status = ScheduledRideStatus.DRIVER_ASSIGNED
    ride.accepted_at = now
    db.add(ride)
    await db.commit()
    await db.refresh(ride)
    return ride, None


async def driver_decline_scheduled_ride(
    db: AsyncSession,
    ride_id: int,
    driver_id: int,
    now: datetime | None = None,
) -> tuple[ScheduledRide | None, str | None]:
    """Driver declines an assigned scheduled ride, returning it to pending.

    Returns:
        (ride, None)          on success.
        (None, error_message) if the ride cannot be declined.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    ride = await get_scheduled_ride(db, ride_id)
    if ride is None:
        return None, "Scheduled ride not found."

    ok, err = is_declinable_by_driver(ride, driver_id)
    if not ok:
        return None, err

    ride.driver_id = None
    ride.status = ScheduledRideStatus.PENDING
    ride.accepted_at = None
    ride.decline_count = (ride.decline_count or 0) + 1
    db.add(ride)
    await db.commit()
    await db.refresh(ride)
    return ride, None


async def cancel_scheduled_ride(
    db: AsyncSession,
    ride_id: int,
    *,
    cancelled_by: CancelledBy,
    reason: str | None = None,
    now: datetime | None = None,
) -> tuple[ScheduledRide | None, str | None]:
    """Cancel a scheduled ride booking.

    Cancellation is allowed from ``pending`` or ``driver_assigned`` status.

    Returns:
        (ride, None)          on success.
        (None, error_message) if cancellation is not allowed.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    ride = await get_scheduled_ride(db, ride_id)
    if ride is None:
        return None, "Scheduled ride not found."

    if not is_cancellable(ride):
        return None, (
            f"Cannot cancel a ride with status '{ride.status.value}'. "
            "Only pending or driver-assigned rides can be cancelled."
        )

    ride.status = ScheduledRideStatus.CANCELLED
    ride.cancelled_by = cancelled_by
    ride.cancellation_reason = reason
    ride.cancelled_at = now
    db.add(ride)
    await db.commit()
    await db.refresh(ride)
    return ride, None


async def get_admin_summary(db: AsyncSession) -> dict[str, int]:
    """Return aggregate status counts across all scheduled rides."""
    result = await db.execute(
        select(ScheduledRide.status, func.count().label("cnt")).group_by(
            ScheduledRide.status
        )
    )
    rows = result.all()
    counts: dict[str, int] = {s.value: 0 for s in ScheduledRideStatus}
    for row in rows:
        counts[row.status.value] = row.cnt
    return {
        "total": sum(counts.values()),
        "pending": counts[ScheduledRideStatus.PENDING.value],
        "driver_assigned": counts[ScheduledRideStatus.DRIVER_ASSIGNED.value],
        "in_progress": counts[ScheduledRideStatus.IN_PROGRESS.value],
        "completed": counts[ScheduledRideStatus.COMPLETED.value],
        "cancelled": counts[ScheduledRideStatus.CANCELLED.value],
    }
