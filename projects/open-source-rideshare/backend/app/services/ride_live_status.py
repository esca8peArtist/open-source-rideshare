"""Ride live-status service.

Provides ``get_ride_live_status`` — a consolidated, poll-friendly snapshot
of a ride's current state for both riders and drivers.

Authorisation
-------------
Caller must satisfy one of:
  - ``ride.rider_id == caller_id``  (the rider who booked)
  - ``ride.driver_id == caller_id`` and ``caller_is_driver``  (assigned driver)
  - ``caller_is_admin``  (platform admin, any ride)

On failure the service raises:
  ``ValueError``       — ride not found
  ``PermissionError``  — caller is not associated with this ride

Distance / ETA model
--------------------
Uses haversine_m from ``app.services.driver_location`` (same helper as
driver_arrival and trip_share).  Speed assumption: 25 km/h (urban average).

    eta_minutes = max(1, round(distance_m / (25_000 / 60)))

Phase messages and poll intervals follow the spec in the endpoint docs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import select

from app.models.driver import DriverProfile
from app.models.ride import Ride, RideStatus
from app.schemas.ride_live_status import RideLiveStatus
from app.services.driver_location import haversine_m

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Urban speed assumption — consistent with driver_arrival and trip_share.
_SPEED_M_PER_MIN: float = 25_000 / 60  # metres per minute at 25 km/h

# Poll interval hints by status (seconds).
_POLL_INTERVALS: dict[RideStatus, int] = {
    RideStatus.SCHEDULED: 60,
    RideStatus.REQUESTED: 5,
    RideStatus.MATCHED: 5,
    RideStatus.DRIVER_EN_ROUTE: 5,
    RideStatus.ARRIVED: 10,
    RideStatus.IN_PROGRESS: 10,
    RideStatus.COMPLETED: 60,
    RideStatus.CANCELLED: 60,
}


def _eta_minutes(distance_m: float) -> int:
    """Return ETA in whole minutes at 25 km/h, minimum 1 minute."""
    return max(1, round(distance_m / _SPEED_M_PER_MIN))


def _iso(dt) -> str | None:
    """Return ISO-8601 string for a datetime, or None."""
    return dt.isoformat() if dt is not None else None


def _build_phase_message(
    status: RideStatus,
    eta_to_pickup: int | None,
    distance_to_pickup_m: float | None,
    eta_to_dropoff: int | None,
) -> str:
    """Return a human-readable phase description for the current ride status.

    Parameters
    ----------
    status:
        The ride's current ``RideStatus``.
    eta_to_pickup:
        Minutes until driver reaches pickup (``DRIVER_EN_ROUTE`` only).
    distance_to_pickup_m:
        Metres from driver to pickup (``DRIVER_EN_ROUTE`` only).
    eta_to_dropoff:
        Minutes until arrival at dropoff (``IN_PROGRESS`` only).
    """
    if status == RideStatus.SCHEDULED:
        return "Your ride is scheduled"
    if status == RideStatus.REQUESTED:
        return "Looking for a driver..."
    if status == RideStatus.MATCHED:
        return "Driver matched, heading to you"
    if status == RideStatus.DRIVER_EN_ROUTE:
        if eta_to_pickup is not None and distance_to_pickup_m is not None:
            dist_m = round(distance_to_pickup_m)
            return f"Driver is {eta_to_pickup} min away ({dist_m} m)"
        return "Driver is on the way"
    if status == RideStatus.ARRIVED:
        return "Your driver has arrived"
    if status == RideStatus.IN_PROGRESS:
        if eta_to_dropoff is not None:
            return f"You're on your way — {eta_to_dropoff} min to destination"
        return "You're on your way"
    if status == RideStatus.COMPLETED:
        return "Ride complete"
    if status == RideStatus.CANCELLED:
        return "Ride cancelled"
    # Fallback for any future status values.
    return status.value.replace("_", " ").title()


async def get_ride_live_status(
    ride_id: int,
    caller_id: int,
    caller_is_driver: bool,
    caller_is_admin: bool,
    db: "AsyncSession",
) -> RideLiveStatus:
    """Return a consolidated live-status snapshot for the given ride.

    Parameters
    ----------
    ride_id:
        Primary key of the ride.
    caller_id:
        ``User.id`` of the authenticated caller.
    caller_is_driver:
        True when the caller's role is ``driver``.
    caller_is_admin:
        True when the caller's role is ``admin``.
    db:
        Async SQLAlchemy session.

    Raises
    ------
    ValueError
        If the ride does not exist.
    PermissionError
        If the caller is not the ride's rider, the ride's assigned driver,
        or a platform admin.
    """
    result = await db.execute(
        select(
            Ride,
            ST_Y(Ride.pickup_location).label("pickup_lat"),
            ST_X(Ride.pickup_location).label("pickup_lng"),
            ST_Y(Ride.dropoff_location).label("dropoff_lat"),
            ST_X(Ride.dropoff_location).label("dropoff_lng"),
        ).where(Ride.id == ride_id)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError("Ride not found")

    ride, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng = row

    # --- Auth guard (404-style to prevent ride-ID enumeration) ---
    is_ride_rider = ride.rider_id == caller_id
    is_ride_driver = caller_is_driver and ride.driver_id == caller_id
    if not (caller_is_admin or is_ride_rider or is_ride_driver):
        raise PermissionError("Not authorised to view this ride")

    # --- Driver GPS ---
    driver_lat: float | None = None
    driver_lng: float | None = None

    if ride.driver_id is not None:
        profile_result = await db.execute(
            select(
                ST_Y(DriverProfile.current_location).label("lat"),
                ST_X(DriverProfile.current_location).label("lng"),
            ).where(DriverProfile.user_id == ride.driver_id)
        )
        profile_row = profile_result.one_or_none()
        if profile_row is not None:
            raw_lat = profile_row.lat
            raw_lng = profile_row.lng
            driver_lat = float(raw_lat) if raw_lat is not None else None
            driver_lng = float(raw_lng) if raw_lng is not None else None

    # --- Distance / ETA to pickup (DRIVER_EN_ROUTE) ---
    distance_to_pickup_m: float | None = None
    eta_to_pickup_minutes: int | None = None

    if (
        ride.status == RideStatus.DRIVER_EN_ROUTE
        and driver_lat is not None
        and driver_lng is not None
    ):
        distance_to_pickup_m = round(
            haversine_m(driver_lat, driver_lng, float(pickup_lat), float(pickup_lng)), 1
        )
        eta_to_pickup_minutes = _eta_minutes(distance_to_pickup_m)

    # --- Distance / ETA to dropoff (IN_PROGRESS) ---
    distance_to_dropoff_m: float | None = None
    eta_to_dropoff_minutes: int | None = None

    if (
        ride.status == RideStatus.IN_PROGRESS
        and driver_lat is not None
        and driver_lng is not None
    ):
        distance_to_dropoff_m = round(
            haversine_m(driver_lat, driver_lng, float(dropoff_lat), float(dropoff_lng)), 1
        )
        eta_to_dropoff_minutes = _eta_minutes(distance_to_dropoff_m)

    # --- Phase message and poll interval ---
    phase_message = _build_phase_message(
        ride.status,
        eta_to_pickup_minutes,
        distance_to_pickup_m,
        eta_to_dropoff_minutes,
    )
    poll_interval = _POLL_INTERVALS.get(ride.status, 10)

    status_value = ride.status.value if hasattr(ride.status, "value") else ride.status

    return RideLiveStatus(
        ride_id=ride_id,
        status=status_value,
        driver_lat=driver_lat,
        driver_lng=driver_lng,
        distance_to_pickup_m=distance_to_pickup_m,
        eta_to_pickup_minutes=eta_to_pickup_minutes,
        distance_to_dropoff_m=distance_to_dropoff_m,
        eta_to_dropoff_minutes=eta_to_dropoff_minutes,
        requested_at=_iso(ride.requested_at),
        driver_matched_at=_iso(ride.matched_at),
        pickup_at=_iso(ride.arrived_at),
        completed_at=_iso(ride.completed_at),
        phase_message=phase_message,
        poll_interval_seconds=poll_interval,
    )
