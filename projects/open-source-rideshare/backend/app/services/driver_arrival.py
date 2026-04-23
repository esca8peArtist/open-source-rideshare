"""Driver arrival countdown service.

Provides ``get_driver_arrival`` — a rider-facing query that returns the
driver's current distance and ETA to the pickup point while the driver is
en route.

ETA model
---------
Distance is computed via haversine math (same as the navigation service).
Speed assumption is 25 km/h (urban average), consistent with trip-share.

    eta_minutes = max(1, round(distance_m / (25_000 / 60)))

Authorisation
-------------
Only the rider who owns the ride (or an admin) may call this endpoint.
The service raises:
  ``ValueError``    — ride not found
  ``PermissionError`` — caller is not the ride's rider (or admin)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import select

from app.models.driver import DriverProfile
from app.models.ride import Ride, RideStatus
from app.schemas.driver_arrival import DriverArrivalResponse
from app.services.driver_location import haversine_m

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Urban speed assumption — consistent with trip_share.py
_SPEED_M_PER_MIN: float = 25_000 / 60  # metres per minute at 25 km/h

# Statuses that indicate the driver is or was heading to pickup
_EN_ROUTE_STATUSES = {RideStatus.DRIVER_EN_ROUTE}

# Statuses where pickup is done (driver already arrived or beyond)
_POST_PICKUP_STATUSES = {
    RideStatus.ARRIVED,
    RideStatus.IN_PROGRESS,
    RideStatus.COMPLETED,
    RideStatus.CANCELLED,
}


def _eta_minutes(distance_m: float) -> int:
    """Return ETA in whole minutes at 25 km/h, minimum 1 minute."""
    return max(1, round(distance_m / _SPEED_M_PER_MIN))


def _build_message(
    status: RideStatus,
    driver_assigned: bool,
    distance_m: float | None,
    eta_min: int | None,
) -> str:
    """Return a human-readable status message for the rider."""
    if not driver_assigned:
        return "Driver not yet assigned"

    if status in _POST_PICKUP_STATUSES:
        status_label = status.value.replace("_", " ").title()
        return f"Ride status: {status_label}"

    # Driver is en route (DRIVER_EN_ROUTE or unrecognised active status)
    if distance_m is None or eta_min is None:
        return "Driver has been assigned but location is unavailable"

    dist_km = distance_m / 1000
    return f"Driver is {dist_km:.1f} km away, arriving in ~{eta_min} minute{'s' if eta_min != 1 else ''}"


async def get_driver_arrival(
    ride_id: int,
    caller_id: int,
    caller_is_admin: bool,
    db: "AsyncSession",
) -> DriverArrivalResponse:
    """Return driver arrival details for the rider.

    Parameters
    ----------
    ride_id:
        Primary key of the ride.
    caller_id:
        ``User.id`` of the authenticated caller.
    caller_is_admin:
        True when the caller holds the ``admin`` role (bypasses ownership check).
    db:
        Async SQLAlchemy session.

    Raises
    ------
    ValueError
        If the ride does not exist.
    PermissionError
        If the caller is not the ride's rider (and is not an admin).
    """
    result = await db.execute(
        select(
            Ride,
            ST_Y(Ride.pickup_location).label("pickup_lat"),
            ST_X(Ride.pickup_location).label("pickup_lng"),
        ).where(Ride.id == ride_id)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError("Ride not found")

    ride, pickup_lat, pickup_lng = row

    if not caller_is_admin and ride.rider_id != caller_id:
        raise PermissionError("Not authorised — only the ride's rider can view arrival details")

    driver_assigned = ride.driver_id is not None
    driver_lat: float | None = None
    driver_lng: float | None = None
    distance_m: float | None = None
    eta_min: int | None = None

    if driver_assigned:
        profile_result = await db.execute(
            select(
                ST_Y(DriverProfile.current_location).label("lat"),
                ST_X(DriverProfile.current_location).label("lng"),
            ).where(DriverProfile.user_id == ride.driver_id)
        )
        profile_row = profile_result.one_or_none()
        if profile_row is not None:
            lat = float(profile_row.lat) if profile_row.lat is not None else None
            lng = float(profile_row.lng) if profile_row.lng is not None else None
            driver_lat = lat
            driver_lng = lng

            if lat is not None and lng is not None:
                distance_m = round(
                    haversine_m(lat, lng, float(pickup_lat), float(pickup_lng)), 1
                )
                eta_min = _eta_minutes(distance_m)

    status_value = ride.status.value if hasattr(ride.status, "value") else ride.status

    message = _build_message(ride.status, driver_assigned, distance_m, eta_min)

    return DriverArrivalResponse(
        ride_id=ride_id,
        status=status_value,
        driver_assigned=driver_assigned,
        driver_lat=driver_lat,
        driver_lng=driver_lng,
        pickup_lat=float(pickup_lat),
        pickup_lng=float(pickup_lng),
        distance_to_pickup_m=distance_m,
        eta_minutes=eta_min,
        message=message,
    )
