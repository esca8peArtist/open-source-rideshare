"""Service layer for recurring rides.

Handles CRUD operations on recurring ride templates and the generation
of individual SCHEDULED rides from active templates.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone

from geoalchemy2.functions import ST_MakePoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recurring_ride import RecurringRide, RecurringRideStatus
from app.models.ride import Ride, RideStatus
from app.services.scheduling import check_overlap

logger = logging.getLogger(__name__)

# How far ahead to generate rides from recurring templates.
GENERATION_HORIZON_HOURS: int = 24

# Maximum recurring rides a single rider can have.
MAX_RECURRING_RIDES_PER_USER: int = 10


class RecurringRideError(Exception):
    """Base error for recurring ride operations."""


class RecurringRideNotFoundError(RecurringRideError):
    pass


class RecurringRideLimitError(RecurringRideError):
    pass


class RecurringRideStateError(RecurringRideError):
    pass


async def create_recurring_ride(
    rider_id: int,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    pickup_address: str,
    dropoff_address: str,
    days_of_week: list[int],
    pickup_time: time,
    tz: str,
    db: AsyncSession,
    *,
    accessibility_required: bool = False,
    label: str | None = None,
    pickup_saved_location_id: int | None = None,
    dropoff_saved_location_id: int | None = None,
) -> RecurringRide:
    """Create a new recurring ride template for a rider."""
    # Check limit
    result = await db.execute(
        select(RecurringRide).where(
            RecurringRide.rider_id == rider_id,
            RecurringRide.status != RecurringRideStatus.CANCELLED,
        )
    )
    existing = result.scalars().all()
    if len(existing) >= MAX_RECURRING_RIDES_PER_USER:
        raise RecurringRideLimitError(
            f"Maximum {MAX_RECURRING_RIDES_PER_USER} recurring rides allowed"
        )

    ride = RecurringRide(
        rider_id=rider_id,
        pickup_location=ST_MakePoint(pickup_lng, pickup_lat, srid=4326),
        dropoff_location=ST_MakePoint(dropoff_lng, dropoff_lat, srid=4326),
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        days_of_week=days_of_week,
        pickup_time=pickup_time,
        timezone=tz,
        accessibility_required=accessibility_required,
        label=label,
        pickup_saved_location_id=pickup_saved_location_id,
        dropoff_saved_location_id=dropoff_saved_location_id,
        status=RecurringRideStatus.ACTIVE,
    )
    db.add(ride)
    await db.commit()
    await db.refresh(ride)
    return ride


async def get_recurring_ride(
    recurring_ride_id: int,
    rider_id: int,
    db: AsyncSession,
) -> RecurringRide:
    """Get a recurring ride by ID, scoped to the rider."""
    result = await db.execute(
        select(RecurringRide).where(
            RecurringRide.id == recurring_ride_id,
            RecurringRide.rider_id == rider_id,
        )
    )
    ride = result.scalar_one_or_none()
    if ride is None:
        raise RecurringRideNotFoundError("Recurring ride not found")
    return ride


async def list_recurring_rides(
    rider_id: int,
    db: AsyncSession,
    *,
    include_cancelled: bool = False,
) -> list[RecurringRide]:
    """List all recurring rides for a rider."""
    query = select(RecurringRide).where(RecurringRide.rider_id == rider_id)
    if not include_cancelled:
        query = query.where(RecurringRide.status != RecurringRideStatus.CANCELLED)
    query = query.order_by(RecurringRide.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_recurring_ride(
    recurring_ride_id: int,
    rider_id: int,
    db: AsyncSession,
    *,
    pickup_lat: float | None = None,
    pickup_lng: float | None = None,
    dropoff_lat: float | None = None,
    dropoff_lng: float | None = None,
    pickup_address: str | None = None,
    dropoff_address: str | None = None,
    days_of_week: list[int] | None = None,
    pickup_time: time | None = None,
    tz: str | None = None,
    accessibility_required: bool | None = None,
    label: str | None = None,
    pickup_saved_location_id: int | None = None,
    dropoff_saved_location_id: int | None = None,
) -> RecurringRide:
    """Update an existing recurring ride template."""
    ride = await get_recurring_ride(recurring_ride_id, rider_id, db)

    if ride.status == RecurringRideStatus.CANCELLED:
        raise RecurringRideStateError("Cannot update a cancelled recurring ride")

    if pickup_lat is not None and pickup_lng is not None:
        ride.pickup_location = ST_MakePoint(pickup_lng, pickup_lat, srid=4326)
    if dropoff_lat is not None and dropoff_lng is not None:
        ride.dropoff_location = ST_MakePoint(dropoff_lng, dropoff_lat, srid=4326)
    if pickup_address is not None:
        ride.pickup_address = pickup_address
    if dropoff_address is not None:
        ride.dropoff_address = dropoff_address
    if days_of_week is not None:
        ride.days_of_week = days_of_week
    if pickup_time is not None:
        ride.pickup_time = pickup_time
    if tz is not None:
        ride.timezone = tz
    if accessibility_required is not None:
        ride.accessibility_required = accessibility_required
    if label is not None:
        ride.label = label
    if pickup_saved_location_id is not None:
        ride.pickup_saved_location_id = pickup_saved_location_id
    if dropoff_saved_location_id is not None:
        ride.dropoff_saved_location_id = dropoff_saved_location_id

    # Reset generation tracking so new schedule takes effect
    ride.last_generated_date = None

    await db.commit()
    await db.refresh(ride)
    return ride


async def pause_recurring_ride(
    recurring_ride_id: int,
    rider_id: int,
    db: AsyncSession,
) -> RecurringRide:
    """Pause a recurring ride (stops generating new rides)."""
    ride = await get_recurring_ride(recurring_ride_id, rider_id, db)
    if ride.status != RecurringRideStatus.ACTIVE:
        raise RecurringRideStateError(
            f"Can only pause active recurring rides (current: {ride.status.value})"
        )
    ride.status = RecurringRideStatus.PAUSED
    await db.commit()
    await db.refresh(ride)
    return ride


async def resume_recurring_ride(
    recurring_ride_id: int,
    rider_id: int,
    db: AsyncSession,
) -> RecurringRide:
    """Resume a paused recurring ride."""
    ride = await get_recurring_ride(recurring_ride_id, rider_id, db)
    if ride.status != RecurringRideStatus.PAUSED:
        raise RecurringRideStateError(
            f"Can only resume paused recurring rides (current: {ride.status.value})"
        )
    ride.status = RecurringRideStatus.ACTIVE
    await db.commit()
    await db.refresh(ride)
    return ride


async def cancel_recurring_ride(
    recurring_ride_id: int,
    rider_id: int,
    db: AsyncSession,
) -> RecurringRide:
    """Cancel a recurring ride (soft delete — stops all future generation)."""
    ride = await get_recurring_ride(recurring_ride_id, rider_id, db)
    if ride.status == RecurringRideStatus.CANCELLED:
        raise RecurringRideStateError("Recurring ride is already cancelled")
    ride.status = RecurringRideStatus.CANCELLED
    await db.commit()
    await db.refresh(ride)
    return ride


async def get_upcoming_generated_rides(
    recurring_ride_id: int,
    db: AsyncSession,
) -> list[Ride]:
    """Get upcoming rides generated from this recurring template."""
    result = await db.execute(
        select(Ride).where(
            Ride.recurring_ride_id == recurring_ride_id,
            Ride.status.in_([RideStatus.SCHEDULED, RideStatus.REQUESTED, RideStatus.MATCHED]),
        ).order_by(Ride.scheduled_for)
    )
    return list(result.scalars().all())


def _next_occurrence_dates(
    days_of_week: list[int],
    pickup_time: time,
    tz_name: str,
    from_date: date,
    horizon_hours: int = GENERATION_HORIZON_HOURS,
) -> list[datetime]:
    """Calculate the next occurrence datetimes within the generation horizon.

    Uses a simple UTC offset approach. For production, this should use
    a proper timezone library (zoneinfo/pytz) but we keep it simple for
    portability across test environments.

    Args:
        days_of_week: ISO weekday numbers (0=Mon .. 6=Sun).
        pickup_time: Local pickup time.
        tz_name: IANA timezone name (used as documentation; UTC assumed for generation).
        from_date: Generate starting from this date (inclusive).
        horizon_hours: How many hours ahead to generate.

    Returns:
        List of UTC datetimes for upcoming ride occurrences.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except (ImportError, KeyError):
        tz = timezone.utc

    horizon_end = datetime.now(timezone.utc) + timedelta(hours=horizon_hours)
    occurrences: list[datetime] = []

    # Check each day in the horizon window
    current = from_date
    max_days = (horizon_hours // 24) + 2  # +2 for timezone edge cases
    for _ in range(max_days):
        if current.weekday() in days_of_week:
            # Combine date + time in rider's timezone
            local_dt = datetime.combine(current, pickup_time, tzinfo=tz)
            utc_dt = local_dt.astimezone(timezone.utc)

            if utc_dt > datetime.now(timezone.utc) and utc_dt <= horizon_end:
                occurrences.append(utc_dt)

        current += timedelta(days=1)

    return occurrences


async def generate_rides_from_recurring(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    horizon_hours: int = GENERATION_HORIZON_HOURS,
) -> int:
    """Generate individual SCHEDULED rides from active recurring templates.

    Called periodically by the dispatch scheduler. For each active recurring
    ride, generates SCHEDULED rides for any upcoming occurrences within the
    horizon that haven't already been generated.

    Returns the number of rides generated.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = await db.execute(
        select(RecurringRide).where(
            RecurringRide.status == RecurringRideStatus.ACTIVE,
        )
    )
    templates = result.scalars().all()

    generated = 0

    for template in templates:
        # Determine start date for generation
        if template.last_generated_date:
            # Start from day after last generated
            from_date = template.last_generated_date.date() + timedelta(days=1)
        else:
            from_date = now.date()

        occurrences = _next_occurrence_dates(
            template.days_of_week,
            template.pickup_time,
            template.timezone,
            from_date,
            horizon_hours,
        )

        if not occurrences:
            continue

        # Get existing scheduled rides for this rider to check overlaps
        existing_result = await db.execute(
            select(Ride.scheduled_for).where(
                Ride.rider_id == template.rider_id,
                Ride.status == RideStatus.SCHEDULED,
                Ride.scheduled_for.isnot(None),
            )
        )
        existing_times = [row[0] for row in existing_result.all()]

        latest_date = template.last_generated_date

        for occurrence_utc in occurrences:
            # Skip if overlap with existing scheduled ride
            overlap = check_overlap(occurrence_utc, existing_times)
            if not overlap.valid:
                logger.debug(
                    "Skipping recurring ride %d occurrence at %s — overlap",
                    template.id,
                    occurrence_utc,
                )
                continue

            # Create the SCHEDULED ride
            ride = Ride(
                rider_id=template.rider_id,
                pickup_location=template.pickup_location,
                dropoff_location=template.dropoff_location,
                pickup_address=template.pickup_address,
                dropoff_address=template.dropoff_address,
                estimated_fare=0.0,  # Will be calculated at dispatch time
                status=RideStatus.SCHEDULED,
                scheduled_for=occurrence_utc,
                accessibility_required=template.accessibility_required,
                recurring_ride_id=template.id,
            )
            db.add(ride)
            existing_times.append(occurrence_utc)  # prevent self-overlap
            generated += 1

            occurrence_date_aware = occurrence_utc.astimezone(timezone.utc)
            if latest_date is None or occurrence_date_aware > (latest_date if latest_date.tzinfo else latest_date.replace(tzinfo=timezone.utc)):
                latest_date = occurrence_date_aware

            logger.info(
                "Generated scheduled ride from recurring template %d for %s",
                template.id,
                occurrence_utc,
            )

        # Update tracking
        if latest_date is not None and latest_date != template.last_generated_date:
            template.last_generated_date = latest_date

    if generated:
        await db.commit()
        logger.info("Generated %d rides from recurring templates", generated)

    return generated
