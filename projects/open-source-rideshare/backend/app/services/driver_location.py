"""Service layer for driver live location tracking.

Drivers push GPS coordinates; riders and admins can query the current
position of a driver during an active ride.

Design: one row per driver in ``driver_locations`` (upsert on each push).
Ride-scoped reads enforce privacy — only the rider matched to an active
ride may query the driver's position; admins can query all active drivers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_location import DriverLocation
from app.models.ride import Ride, RideStatus
from app.schemas.driver_location import LocationUpdate


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


# Ride statuses during which the driver is physically moving toward
# or transporting the rider — location should be visible.
_TRACKABLE_STATUSES = {
    RideStatus.DRIVER_EN_ROUTE,
    RideStatus.ARRIVED,
    RideStatus.IN_PROGRESS,
}


# ---------------------------------------------------------------------------
# Driver writes
# ---------------------------------------------------------------------------

async def upsert_driver_location(
    db: AsyncSession,
    driver_id: int,
    data: LocationUpdate,
) -> DriverLocation:
    """Create or update the driver's location record.

    If ``data.ride_id`` is provided we verify the driver is actually assigned
    to that ride before recording it; otherwise ride_id is left as-is from
    any existing record (or NULL for a fresh row).
    """
    # Validate ride_id ownership if supplied
    if data.ride_id is not None:
        result = await db.execute(
            select(Ride).where(
                Ride.id == data.ride_id,
                Ride.driver_id == driver_id,
            )
        )
        ride = result.scalar_one_or_none()
        if ride is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ride_id does not correspond to an active ride assigned to you.",
            )

    # Load existing record (one per driver)
    result = await db.execute(
        select(DriverLocation).where(DriverLocation.driver_id == driver_id)
    )
    loc = result.scalar_one_or_none()

    if loc is None:
        loc = DriverLocation(
            driver_id=driver_id,
            latitude=data.latitude,
            longitude=data.longitude,
            accuracy_meters=data.accuracy_meters,
            heading=data.heading,
            speed_kmh=data.speed_kmh,
            ride_id=data.ride_id,
            is_active=True,
        )
        db.add(loc)
    else:
        loc.latitude = data.latitude
        loc.longitude = data.longitude
        loc.accuracy_meters = data.accuracy_meters
        loc.heading = data.heading
        loc.speed_kmh = data.speed_kmh
        loc.is_active = True
        if data.ride_id is not None:
            loc.ride_id = data.ride_id

    await db.commit()
    await db.refresh(loc)
    return loc


async def clear_driver_location(
    db: AsyncSession,
    driver_id: int,
) -> None:
    """Mark a driver as inactive (called on shift end or clock-out)."""
    result = await db.execute(
        select(DriverLocation).where(DriverLocation.driver_id == driver_id)
    )
    loc = result.scalar_one_or_none()
    if loc is not None:
        loc.is_active = False
        loc.ride_id = None
        await db.commit()


# ---------------------------------------------------------------------------
# Rider / public reads
# ---------------------------------------------------------------------------

async def get_ride_driver_location(
    db: AsyncSession,
    ride_id: int,
    requester_id: int,
) -> DriverLocation:
    """Return the driver's current location for an active ride.

    Authorization: the requester must be either the rider or the driver on
    the ride.  The ride must be in a trackable status (en_route / arrived /
    in_progress).
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if ride is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found.",
        )

    # Auth: rider or driver only
    if requester_id not in (ride.rider_id, ride.driver_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this ride.",
        )

    # Ride must be in an active / trackable status
    if ride.status not in _TRACKABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Live tracking is only available while the ride is in one of "
                f"{[s.value for s in _TRACKABLE_STATUSES]}. "
                f"Current status: {ride.status}."
            ),
        )

    if ride.driver_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driver is assigned to this ride yet.",
        )

    result = await db.execute(
        select(DriverLocation).where(DriverLocation.driver_id == ride.driver_id)
    )
    loc = result.scalar_one_or_none()
    if loc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver has not broadcast a location yet.",
        )
    return loc


# ---------------------------------------------------------------------------
# Admin reads
# ---------------------------------------------------------------------------

async def list_active_drivers(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DriverLocation], int]:
    """Return all drivers currently marked is_active=True with pagination."""
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).select_from(DriverLocation).where(
            DriverLocation.is_active == True  # noqa: E712
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(DriverLocation)
        .where(DriverLocation.is_active == True)  # noqa: E712
        .order_by(DriverLocation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    locations = list(result.scalars().all())
    return locations, total
