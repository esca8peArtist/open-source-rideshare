"""Driver in-ride navigation service.

Provides navigation state for drivers during an active ride:
  - Ordered list of stops: pickup → waypoints → dropoff
  - Distance and ETA to each remaining stop from driver's current position
  - Automatic route deviation detection using cross-track distance

Deviation detection
-------------------
Cross-track distance measures how far a point is from the straight-line path
between two coordinates.  When a driver's position exceeds DEVIATION_THRESHOLD_KM
from the line connecting their last completed stop to their next pending stop,
route_deviation_flagged_at is set on the ride (once only).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.waypoint import RideWaypoint, WaypointStatus
from app.schemas.driver_navigation import (
    NavigationStateResponse,
    NavigationStop,
    StopStatus,
    StopType,
)

# Speed assumption (km/h) — consistent with ETA and dispatch engine.
AVG_SPEED_KMH: float = 30.0

# Cross-track deviation threshold.  If the driver is > 500 m off the straight-line
# corridor between their last stop and their next stop, flag a deviation.
DEVIATION_THRESHOLD_KM: float = 0.5

# Earth radius used in haversine and cross-track calculations (km).
_EARTH_RADIUS_KM: float = 6371.0


# ---------------------------------------------------------------------------
# Geometry helpers (pure functions — no DB dependency)
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in km between two lat/lng points."""
    rlat1, rlng1, rlat2, rlng2 = (math.radians(x) for x in (lat1, lng1, lat2, lng2))
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _bearing_rad(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the initial bearing (radians) from point 1 to point 2."""
    rlat1, rlng1, rlat2, rlng2 = (math.radians(x) for x in (lat1, lng1, lat2, lng2))
    dlng = rlng2 - rlng1
    x = math.sin(dlng) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlng)
    return math.atan2(x, y)


def cross_track_distance_km(
    point_lat: float,
    point_lng: float,
    path_start_lat: float,
    path_start_lng: float,
    path_end_lat: float,
    path_end_lng: float,
) -> float:
    """Return the perpendicular distance (km) from a point to a great-circle path.

    Uses the standard cross-track distance formula.  Always returns a non-negative value.
    """
    d13 = haversine_km(path_start_lat, path_start_lng, point_lat, point_lng)
    if d13 == 0.0:
        return 0.0

    theta13 = _bearing_rad(path_start_lat, path_start_lng, point_lat, point_lng)
    theta12 = _bearing_rad(path_start_lat, path_start_lng, path_end_lat, path_end_lng)

    angular_dist = d13 / _EARTH_RADIUS_KM
    cross = math.asin(math.sin(angular_dist) * math.sin(theta13 - theta12))
    return abs(cross * _EARTH_RADIUS_KM)


def _eta_minutes(distance_km: float) -> int:
    """Return ceil(distance / speed * 60), minimum 1 minute."""
    if distance_km <= 0.0:
        return 1
    return max(1, math.ceil(distance_km / AVG_SPEED_KMH * 60.0))


# ---------------------------------------------------------------------------
# Stop building helpers (pure — accept pre-resolved coords)
# ---------------------------------------------------------------------------

def _waypoint_status(wp: RideWaypoint) -> StopStatus:
    if wp.status == WaypointStatus.SKIPPED:
        return StopStatus.SKIPPED
    if wp.status in (WaypointStatus.ARRIVED, WaypointStatus.DEPARTED):
        return StopStatus.COMPLETED
    return StopStatus.PENDING


def build_stops(
    ride: Ride,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    waypoints: list[RideWaypoint],
    driver_lat: Optional[float],
    driver_lng: Optional[float],
) -> list[NavigationStop]:
    """Build ordered stop list: pickup → waypoints (sorted) → dropoff."""
    stops: list[NavigationStop] = []

    pickup_done = ride.status in (
        RideStatus.IN_PROGRESS, RideStatus.COMPLETED, RideStatus.CANCELLED
    )
    stops.append(
        NavigationStop(
            type=StopType.PICKUP,
            index=0,
            address=ride.pickup_address,
            lat=pickup_lat,
            lng=pickup_lng,
            status=StopStatus.COMPLETED if pickup_done else StopStatus.PENDING,
            arrived_at=ride.arrived_at,
            departed_at=ride.started_at,
        )
    )

    for wp in sorted(waypoints, key=lambda w: w.order):
        stops.append(
            NavigationStop(
                type=StopType.WAYPOINT,
                index=len(stops),
                address=wp.address,
                lat=wp.lat,
                lng=wp.lng,
                status=_waypoint_status(wp),
                waypoint_id=wp.id,
                wait_time_minutes=wp.wait_time_minutes,
                arrived_at=wp.actual_arrival_at,
                departed_at=wp.departed_at,
            )
        )

    dropoff_done = ride.status == RideStatus.COMPLETED
    stops.append(
        NavigationStop(
            type=StopType.DROPOFF,
            index=len(stops),
            address=ride.dropoff_address,
            lat=dropoff_lat,
            lng=dropoff_lng,
            status=StopStatus.COMPLETED if dropoff_done else StopStatus.PENDING,
        )
    )

    # Annotate distances / ETAs for pending stops
    if driver_lat is not None and driver_lng is not None:
        for stop in stops:
            if stop.status == StopStatus.PENDING:
                dist = haversine_km(driver_lat, driver_lng, stop.lat, stop.lng)
                stop.distance_km = round(dist, 3)
                stop.eta_minutes = _eta_minutes(dist)

    return stops


def find_next_stop(stops: list[NavigationStop]) -> Optional[NavigationStop]:
    """Return the first pending stop, or None if all stops are done."""
    for stop in stops:
        if stop.status == StopStatus.PENDING:
            return stop
    return None


def total_remaining(
    stops: list[NavigationStop],
    driver_lat: Optional[float],
    driver_lng: Optional[float],
) -> tuple[float, int]:
    """Return (total_km, total_minutes) along the chain: driver → each remaining stop."""
    pending = [s for s in stops if s.status == StopStatus.PENDING]
    if not pending or driver_lat is None or driver_lng is None:
        return 0.0, 0

    total_km = 0.0
    prev_lat, prev_lng = driver_lat, driver_lng
    for stop in pending:
        total_km += haversine_km(prev_lat, prev_lng, stop.lat, stop.lng)
        prev_lat, prev_lng = stop.lat, stop.lng

    total_km = round(total_km, 3)
    return total_km, _eta_minutes(total_km)


def is_deviation(
    stops: list[NavigationStop],
    driver_lat: float,
    driver_lng: float,
) -> bool:
    """Return True if the driver's cross-track distance exceeds DEVIATION_THRESHOLD_KM."""
    completed = [s for s in stops if s.status == StopStatus.COMPLETED]
    pending = [s for s in stops if s.status == StopStatus.PENDING]

    if not pending:
        return False

    next_stop = pending[0]

    if completed:
        prev_stop = completed[-1]
        xtd = cross_track_distance_km(
            driver_lat, driver_lng,
            prev_stop.lat, prev_stop.lng,
            next_stop.lat, next_stop.lng,
        )
    else:
        xtd = haversine_km(driver_lat, driver_lng, next_stop.lat, next_stop.lng)

    return xtd > DEVIATION_THRESHOLD_KM


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

async def _fetch_ride_with_coords(ride_id: int, db: AsyncSession):
    """Query ride ORM object plus extracted lat/lng from PostGIS geometry."""
    result = await db.execute(
        select(
            Ride,
            ST_Y(Ride.pickup_location).label("pickup_lat"),
            ST_X(Ride.pickup_location).label("pickup_lng"),
            ST_Y(Ride.dropoff_location).label("dropoff_lat"),
            ST_X(Ride.dropoff_location).label("dropoff_lng"),
        ).where(Ride.id == ride_id)
    )
    return result.one_or_none()


async def _fetch_waypoints(ride_id: int, db: AsyncSession) -> list[RideWaypoint]:
    result = await db.execute(
        select(RideWaypoint).where(RideWaypoint.ride_id == ride_id)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def get_navigation_state(
    ride_id: int,
    driver_id: int,
    db: AsyncSession,
    driver_lat: Optional[float] = None,
    driver_lng: Optional[float] = None,
) -> NavigationStateResponse:
    """Return the current navigation state for a ride.

    If driver_lat/driver_lng are omitted, distances and ETAs are omitted.
    Raises ValueError for ride not found, PermissionError if not the ride's driver.
    """
    row = await _fetch_ride_with_coords(ride_id, db)
    if row is None:
        raise ValueError("Ride not found")

    ride, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng = row

    if ride.driver_id != driver_id:
        raise PermissionError("Not authorized — only the assigned driver can view navigation")

    waypoints = await _fetch_waypoints(ride_id, db)
    stops = build_stops(
        ride, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
        waypoints, driver_lat, driver_lng,
    )
    ns = find_next_stop(stops)
    total_km, total_min = total_remaining(stops, driver_lat, driver_lng)

    return NavigationStateResponse(
        ride_id=ride_id,
        ride_status=ride.status.value if hasattr(ride.status, "value") else ride.status,
        stops=stops,
        next_stop=ns,
        current_stop_index=ns.index if ns else None,
        driver_lat=driver_lat,
        driver_lng=driver_lng,
        route_deviation_flagged=ride.route_deviation_flagged_at is not None,
        total_remaining_km=total_km,
        total_remaining_minutes=total_min,
    )


async def update_navigation_position(
    ride_id: int,
    driver_id: int,
    lat: float,
    lng: float,
    db: AsyncSession,
) -> NavigationStateResponse:
    """Process a driver position update and return updated navigation state.

    Flags route deviation if the driver exceeds DEVIATION_THRESHOLD_KM from the direct
    corridor between their last completed stop and next pending stop.
    Only active rides (DRIVER_EN_ROUTE, ARRIVED, IN_PROGRESS) accept position updates.
    Raises ValueError for ride not found or wrong status, PermissionError if not the driver.
    """
    row = await _fetch_ride_with_coords(ride_id, db)
    if row is None:
        raise ValueError("Ride not found")

    ride, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng = row

    if ride.driver_id != driver_id:
        raise PermissionError("Not authorized — only the assigned driver can submit position updates")

    active_statuses = {RideStatus.DRIVER_EN_ROUTE, RideStatus.ARRIVED, RideStatus.IN_PROGRESS}
    if ride.status not in active_statuses:
        raise ValueError(
            f"Position updates only accepted for active rides (got: {ride.status.value})"
        )

    waypoints = await _fetch_waypoints(ride_id, db)
    stops = build_stops(
        ride, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
        waypoints, lat, lng,
    )

    # Flag deviation if not already flagged
    if ride.route_deviation_flagged_at is None and is_deviation(stops, lat, lng):
        await db.execute(
            update(Ride)
            .where(Ride.id == ride.id)
            .values(route_deviation_flagged_at=datetime.now(timezone.utc))
        )
        await db.commit()
        deviation_flagged = True
    else:
        deviation_flagged = ride.route_deviation_flagged_at is not None

    ns = find_next_stop(stops)
    total_km, total_min = total_remaining(stops, lat, lng)

    return NavigationStateResponse(
        ride_id=ride_id,
        ride_status=ride.status.value if hasattr(ride.status, "value") else ride.status,
        stops=stops,
        next_stop=ns,
        current_stop_index=ns.index if ns else None,
        driver_lat=lat,
        driver_lng=lng,
        route_deviation_flagged=deviation_flagged,
        total_remaining_km=total_km,
        total_remaining_minutes=total_min,
    )
