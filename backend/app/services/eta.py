"""Driver ETA estimation service.

Uses OSRM for accurate routing when available, with haversine-based
fallback for graceful degradation.  Reads driver locations from the
Redis geo set maintained by the matching engine.
"""

import logging
import math
from dataclasses import dataclass

import redis.asyncio as redis

from app.config import settings
from app.services.matching import REDIS_DRIVER_GEO_KEY

logger = logging.getLogger(__name__)

# Average city driving speed for haversine fallback (km/h)
FALLBACK_SPEED_KMH = 25.0

# Earth radius in km (WGS-84 mean)
EARTH_RADIUS_KM = 6371.0


@dataclass
class DriverLocation:
    lat: float
    lng: float


@dataclass
class ETAEstimate:
    eta_minutes: float
    distance_km: float
    driver_lat: float
    driver_lng: float
    source: str  # "osrm" or "haversine"


@dataclass
class TripETA:
    """Combined ETA: driver-to-pickup + pickup-to-dropoff."""
    pickup_eta_minutes: float
    pickup_distance_km: float
    trip_duration_minutes: float
    trip_distance_km: float
    total_minutes: float
    driver_lat: float
    driver_lng: float
    source: str


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return straight-line distance in km between two lat/lng points."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def haversine_eta(distance_km: float, speed_kmh: float = FALLBACK_SPEED_KMH) -> float:
    """Estimate travel time in minutes from distance and average speed."""
    if speed_kmh <= 0:
        return 0.0
    return (distance_km / speed_kmh) * 60.0


async def get_driver_location(
    redis_client: redis.Redis, driver_user_id: int
) -> DriverLocation | None:
    """Look up a driver's last-known position from the Redis geo set."""
    positions = await redis_client.geopos(
        REDIS_DRIVER_GEO_KEY, str(driver_user_id)
    )
    if not positions or positions[0] is None:
        return None
    lng, lat = positions[0]
    return DriverLocation(lat=float(lat), lng=float(lng))


async def estimate_driver_eta(
    redis_client: redis.Redis,
    driver_user_id: int,
    pickup_lat: float,
    pickup_lng: float,
) -> ETAEstimate | None:
    """Estimate how long until *driver_user_id* reaches the pickup point.

    Tries OSRM first for road-network routing; falls back to haversine
    with a city-speed assumption if OSRM is unavailable.

    Returns ``None`` if the driver's location is unknown.
    """
    location = await get_driver_location(redis_client, driver_user_id)
    if location is None:
        return None

    # Try OSRM routing
    try:
        from app.services.routing import get_route

        route = await get_route(
            location.lat, location.lng, pickup_lat, pickup_lng
        )
        return ETAEstimate(
            eta_minutes=round(route["duration_min"], 1),
            distance_km=round(route["distance_km"], 2),
            driver_lat=location.lat,
            driver_lng=location.lng,
            source="osrm",
        )
    except Exception:
        logger.debug(
            "OSRM unavailable for ETA (driver %d) — using haversine fallback",
            driver_user_id,
        )

    # Haversine fallback — multiply straight-line distance by 1.4 to
    # approximate road distance in a typical urban grid.
    straight = haversine_distance(
        location.lat, location.lng, pickup_lat, pickup_lng
    )
    road_approx = straight * 1.4
    minutes = haversine_eta(road_approx)

    return ETAEstimate(
        eta_minutes=round(minutes, 1),
        distance_km=round(road_approx, 2),
        driver_lat=location.lat,
        driver_lng=location.lng,
        source="haversine",
    )


async def estimate_trip_eta(
    redis_client: redis.Redis,
    driver_user_id: int,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
) -> TripETA | None:
    """Estimate full trip time: driver→pickup + pickup→dropoff.

    Returns ``None`` if the driver location is unknown.
    """
    pickup_eta = await estimate_driver_eta(
        redis_client, driver_user_id, pickup_lat, pickup_lng
    )
    if pickup_eta is None:
        return None

    # Trip segment: pickup → dropoff
    try:
        from app.services.routing import get_route

        route = await get_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
        trip_minutes = round(route["duration_min"], 1)
        trip_km = round(route["distance_km"], 2)
    except Exception:
        straight = haversine_distance(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
        road_approx = straight * 1.4
        trip_minutes = round(haversine_eta(road_approx), 1)
        trip_km = round(road_approx, 2)

    return TripETA(
        pickup_eta_minutes=pickup_eta.eta_minutes,
        pickup_distance_km=pickup_eta.distance_km,
        trip_duration_minutes=trip_minutes,
        trip_distance_km=trip_km,
        total_minutes=round(pickup_eta.eta_minutes + trip_minutes, 1),
        driver_lat=pickup_eta.driver_lat,
        driver_lng=pickup_eta.driver_lng,
        source=pickup_eta.source,
    )
