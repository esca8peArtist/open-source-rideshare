"""Route deviation detection for active rides.

When a driver submits a location update during an IN_PROGRESS ride, this
service checks whether the driver has deviated significantly from the
direct path between pickup and dropoff.

Deviation is measured as the cross-track distance — the perpendicular
distance from the driver's current position to the great-circle line
connecting pickup to dropoff.  This is the standard formula from
Movable Type Scripts (http://www.movable-type.co.uk/scripts/latlong.html).

If the deviation exceeds the threshold and the ride hasn't already been
flagged, the rider is notified (push + SMS) and the flag is persisted so
the alert fires only once per ride.

Usage
-----
Called fire-and-forget from the driver location update endpoint:

    asyncio.ensure_future(
        check_and_notify_deviation(user_id=driver_user_id, lat=lat, lng=lng, db=db)
    )
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default cross-track threshold: flag if driver is more than 1 km off the
# pickup→dropoff line.  Configurable via check_and_notify_deviation's
# threshold_m parameter.
DEFAULT_DEVIATION_THRESHOLD_M = 1_000


# ---------------------------------------------------------------------------
# Pure geometry helpers
# ---------------------------------------------------------------------------


def _bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the initial bearing (radians) from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lam = math.radians(lng2 - lng1)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lam)
    y = math.sin(d_lam) * math.cos(phi2)
    return math.atan2(y, x)


def _angular_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the angular distance (radians) between two WGS-84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * math.asin(math.sqrt(a))


def cross_track_distance_m(
    driver_lat: float,
    driver_lng: float,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    earth_radius_m: float = 6_371_000,
) -> float:
    """Return the cross-track distance (metres) from the driver's position to the
    pickup→dropoff great-circle line.

    Cross-track distance is the shortest distance from a point to a great-circle
    path.  A positive value means the driver is to the right of the path when
    facing from pickup to dropoff; negative means left.  We return the absolute
    value since direction doesn't matter for deviation detection.

    Formula:
        d_xt = asin(sin(delta_AP / R) × sin(theta_AP − theta_AB)) × R

    where delta_AP is the angular distance from pickup (A) to driver (P),
    theta_AB is the bearing A→B (dropoff), and theta_AP is the bearing A→P.
    """
    delta_ap = _angular_distance(pickup_lat, pickup_lng, driver_lat, driver_lng)
    theta_ab = _bearing(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    theta_ap = _bearing(pickup_lat, pickup_lng, driver_lat, driver_lng)

    d_xt = math.asin(math.sin(delta_ap) * math.sin(theta_ap - theta_ab)) * earth_radius_m
    return abs(d_xt)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _get_ride_geometry(
    db: AsyncSession, ride_id: int
) -> tuple[float, float, float, float] | None:
    """Return (pickup_lat, pickup_lng, dropoff_lat, dropoff_lng) for a ride.

    Returns None if the ride is not found or has no geometry.
    """
    from geoalchemy2.functions import ST_X, ST_Y
    from sqlalchemy import select

    from app.models.ride import Ride

    result = await db.execute(
        select(
            ST_Y(Ride.pickup_location).label("pickup_lat"),
            ST_X(Ride.pickup_location).label("pickup_lng"),
            ST_Y(Ride.dropoff_location).label("dropoff_lat"),
            ST_X(Ride.dropoff_location).label("dropoff_lng"),
        ).where(Ride.id == ride_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return float(row.pickup_lat), float(row.pickup_lng), float(row.dropoff_lat), float(row.dropoff_lng)


async def _find_active_ride_for_driver(db: AsyncSession, driver_user_id: int) -> int | None:
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def check_and_notify_deviation(
    user_id: int,
    lat: float,
    lng: float,
    db: AsyncSession,
    threshold_m: float = DEFAULT_DEVIATION_THRESHOLD_M,
) -> bool:
    """Check whether the driver (identified by their user_id) has deviated from
    their active ride's route.  If so, flag the ride and notify the rider.

    Returns True if a new deviation was detected and the rider was notified,
    False otherwise (no active ride, already flagged, within threshold, or error).

    This function is designed to be called fire-and-forget.  Any exception is
    caught and logged so that location updates are never blocked.
    """
    try:
        from datetime import datetime, timezone

        from sqlalchemy import select, update

        from app.models.ride import Ride, RideStatus
        from app.services.notification_events import notify_route_deviation

        # 1. Find the driver's active IN_PROGRESS ride
        ride_id = await _find_active_ride_for_driver(db, user_id)
        if ride_id is None:
            return False

        # 2. Fetch the ride to check if already flagged
        result = await db.execute(
            select(Ride.route_deviation_flagged_at, Ride.rider_id, Ride.dropoff_address).where(
                Ride.id == ride_id
            )
        )
        row = result.one_or_none()
        if row is None or row.route_deviation_flagged_at is not None:
            # Already flagged — don't re-notify
            return False

        rider_id = row.rider_id
        dropoff_address = row.dropoff_address or ""

        # 3. Get ride geometry
        geometry = await _get_ride_geometry(db, ride_id)
        if geometry is None:
            logger.warning("Route deviation check skipped — no geometry for ride %d", ride_id)
            return False

        pickup_lat, pickup_lng, dropoff_lat, dropoff_lng = geometry

        # 4. Check if pickup and dropoff are the same point (pathological case)
        if pickup_lat == dropoff_lat and pickup_lng == dropoff_lng:
            return False

        # 5. Calculate cross-track distance
        deviation_m = cross_track_distance_m(
            driver_lat=lat,
            driver_lng=lng,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            dropoff_lat=dropoff_lat,
            dropoff_lng=dropoff_lng,
        )

        if deviation_m <= threshold_m:
            return False

        # 6. Persist the flag (idempotent — only set once)
        now = datetime.now(timezone.utc)
        await db.execute(
            update(Ride)
            .where(Ride.id == ride_id, Ride.route_deviation_flagged_at.is_(None))
            .values(route_deviation_flagged_at=now)
        )
        await db.commit()

        # 7. Notify the rider (fire-and-forget, exception-safe)
        await notify_route_deviation(
            db=db,
            rider_id=rider_id,
            ride_id=ride_id,
            dropoff_address=dropoff_address,
        )

        logger.info(
            "Route deviation flagged for ride %d (driver user %d, %.0f m off route)",
            ride_id,
            user_id,
            deviation_m,
        )
        return True

    except Exception:
        logger.exception(
            "Unexpected error in route deviation check for driver user %d", user_id
        )
        return False
