"""Driver geofence exit detection.

When a driver submits a location update during an IN_PROGRESS ride, this
service checks whether the driver is still within at least one active
service area.  If the driver has exited all service areas and the ride
has not already been alerted, both the rider and the driver are notified
and the flag is persisted (fires only once per ride).

Usage
-----
Called fire-and-forget from the driver location update endpoint:

    asyncio.ensure_future(
        check_and_notify_geofence_exit(user_id=driver_user_id, lat=lat, lng=lng, db=db)
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _find_active_ride_id(db: AsyncSession, driver_user_id: int) -> int | None:
    """Return the ride_id of the driver's current IN_PROGRESS ride, or None."""
    from sqlalchemy import select

    from app.models.ride import Ride, RideStatus

    result = await db.execute(
        select(Ride.id).where(
            Ride.driver_id == driver_user_id,
            Ride.status == RideStatus.IN_PROGRESS,
        )
    )
    row = result.first()
    return row[0] if row else None


async def _get_ride_alert_info(db: AsyncSession, ride_id: int):
    """Return (geofence_exit_alerted_at, rider_id) for the ride, or None."""
    from sqlalchemy import select

    from app.models.ride import Ride

    result = await db.execute(
        select(Ride.geofence_exit_alerted_at, Ride.rider_id).where(Ride.id == ride_id)
    )
    return result.one_or_none()


async def _any_active_service_areas(db: AsyncSession) -> bool:
    """Return True if at least one active service area exists."""
    from sqlalchemy import select

    from app.models.service_area import ServiceArea

    result = await db.execute(
        select(ServiceArea.id).where(ServiceArea.is_active.is_(True)).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _driver_within_any_service_area(db: AsyncSession, lat: float, lng: float) -> bool:
    """Return True if (lat, lng) is contained by at least one active service area."""
    from geoalchemy2.functions import ST_Contains, ST_MakePoint
    from sqlalchemy import select

    from app.models.service_area import ServiceArea

    result = await db.execute(
        select(ServiceArea.id)
        .where(
            ServiceArea.is_active.is_(True),
            ST_Contains(ServiceArea.boundary, ST_MakePoint(lng, lat, 4326)),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def check_and_notify_geofence_exit(
    user_id: int,
    lat: float,
    lng: float,
    db: AsyncSession,
) -> bool:
    """Check whether the driver has left all active service areas during an IN_PROGRESS ride.

    If so, flag the ride (idempotent — fires once per ride) and notify both the rider
    and the driver.

    Returns True if a new geofence exit was detected and notifications dispatched.
    Returns False if there is no active ride, the ride is already flagged, the driver
    is inside a service area, no service areas are configured, or an error occurs.

    Designed to be called fire-and-forget — exceptions are caught and logged so that
    location updates are never blocked.
    """
    try:
        from sqlalchemy import update

        from app.models.ride import Ride
        from app.services.notification_events import (
            notify_driver_geofence_exit,
            notify_geofence_exit,
        )

        # 1. Find the driver's active IN_PROGRESS ride
        ride_id = await _find_active_ride_id(db, user_id)
        if ride_id is None:
            return False

        # 2. Fetch alert state — skip if already alerted
        row = await _get_ride_alert_info(db, ride_id)
        if row is None or row.geofence_exit_alerted_at is not None:
            return False

        rider_id = row.rider_id

        # 3. Skip if no service areas configured (boundary not yet defined)
        if not await _any_active_service_areas(db):
            return False

        # 4. Check if driver is still within at least one service area
        if await _driver_within_any_service_area(db, lat, lng):
            return False

        # 5. Persist the flag (IS NULL guard ensures idempotency across concurrent calls)
        now = datetime.now(timezone.utc)
        await db.execute(
            update(Ride)
            .where(Ride.id == ride_id, Ride.geofence_exit_alerted_at.is_(None))
            .values(geofence_exit_alerted_at=now)
        )
        await db.commit()

        # 6. Notify rider and driver (fire-and-forget, exception-safe)
        await notify_geofence_exit(db=db, rider_id=rider_id, ride_id=ride_id)
        await notify_driver_geofence_exit(db=db, driver_user_id=user_id, ride_id=ride_id)

        logger.info(
            "Geofence exit flagged for ride %d (driver user %d, lat=%.4f lng=%.4f)",
            ride_id,
            user_id,
            lat,
            lng,
        )
        return True

    except Exception:
        logger.exception(
            "Unexpected error in geofence exit check for driver user %d", user_id
        )
        return False
