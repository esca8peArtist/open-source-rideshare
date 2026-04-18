"""GET /rides/eta/estimate — public pre-booking ETA estimate.

Lets a rider see an estimated arrival time and trip duration before they
tap "Request Ride".  No authentication is required, and no ride record
needs to exist yet.

Endpoint
--------
GET /rides/eta/estimate
    ?pickup_lat={lat}
    &pickup_lng={lng}
    &dropoff_lat={lat}
    &dropoff_lng={lng}

Parameters
----------
pickup_lat   required float  Pickup latitude   (-90  to  90)
pickup_lng   required float  Pickup longitude  (-180 to 180)
dropoff_lat  required float  Dropoff latitude  (-90  to  90)
dropoff_lng  required float  Dropoff longitude (-180 to 180)

Response
--------
{
  "pickup_eta_minutes":        int,          // ceil(nearest_driver_km / 30 km/h); 15 if no drivers
  "trip_duration_minutes":     int,          // ceil(pickup→dropoff km / 30 km/h), min 2
  "nearest_driver_distance_km": float | null, // distance to closest available driver
  "available_driver_count":    int,          // drivers within 10 km
  "confidence": "high"|"medium"|"low"       // high ≥3, medium 1–2, low 0
}

Calculation rules
-----------------
- Speed assumption: 30 km/h for both pickup ETA and trip duration (matches
  the rest of the codebase, see AVG_SPEED_KMH in drivers_nearby.py).
- Pickup ETA uses math.ceil so riders are never shown an ETA that's too
  optimistic.  Minimum is 1 minute for any non-zero distance.
- Trip duration minimum is 2 minutes (avoids showing "0 min" for very
  short trips).
- Search radius for available drivers is fixed at 10 km, matching the
  dispatch engine's practical operational radius.
- Driver availability definition: is_online=True, is_on_break=False,
  heartbeat within 5 minutes — identical to GET /drivers/nearby.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.eta_estimate import ETAEstimateResponse
from app.services.drivers_nearby import (
    AVG_SPEED_KMH,
    get_nearby_available_drivers_km,
    haversine_km,
)

router = APIRouter(tags=["rides"])

# Search radius used when looking for available drivers near the pickup.
_DRIVER_SEARCH_RADIUS_KM: float = 10.0

# Fallback pickup ETA (minutes) when no drivers are found within the radius.
_NO_DRIVER_FALLBACK_ETA_MINUTES: int = 15

# Minimum trip duration returned, even for zero-distance trips.
_MIN_TRIP_DURATION_MINUTES: int = 2


def _pickup_eta_minutes(distance_km: float) -> int:
    """Return ceil(distance / speed * 60), minimum 1 minute for any non-zero distance."""
    if distance_km <= 0.0:
        return 1
    return max(1, math.ceil(distance_km / AVG_SPEED_KMH * 60.0))


def _trip_duration_minutes(distance_km: float) -> int:
    """Return ceil(distance / speed * 60), minimum _MIN_TRIP_DURATION_MINUTES."""
    if distance_km <= 0.0:
        return _MIN_TRIP_DURATION_MINUTES
    raw = math.ceil(distance_km / AVG_SPEED_KMH * 60.0)
    return max(_MIN_TRIP_DURATION_MINUTES, raw)


def _confidence(driver_count: int) -> str:
    """Map driver count to a confidence level string."""
    if driver_count >= 3:
        return "high"
    if driver_count >= 1:
        return "medium"
    return "low"


@router.get(
    "/rides/eta/estimate",
    response_model=ETAEstimateResponse,
    summary="Pre-booking ETA estimate (no auth required)",
    description=(
        "Returns an estimated pickup ETA and trip duration before the rider commits "
        "to a booking. Requires no authentication. "
        "The pickup ETA is based on the nearest available driver within 10 km; "
        "a static 15-minute fallback is used when no drivers are found. "
        "Confidence reflects how many drivers were found: "
        "high (≥3), medium (1–2), or low (0)."
    ),
)
async def get_eta_estimate(
    pickup_lat: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description="Pickup latitude (-90 to 90)",
    ),
    pickup_lng: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description="Pickup longitude (-180 to 180)",
    ),
    dropoff_lat: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description="Dropoff latitude (-90 to 90)",
    ),
    dropoff_lng: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description="Dropoff longitude (-180 to 180)",
    ),
    db: AsyncSession = Depends(get_db),
) -> ETAEstimateResponse:
    """Estimate pickup ETA and trip duration for a prospective ride.

    Queries available drivers near the pickup location (10 km radius) using
    the same availability definition as the dispatch engine.  No ride record
    is created or required.
    """
    # Find available drivers near the pickup point.
    nearby_drivers = await get_nearby_available_drivers_km(
        db, pickup_lat, pickup_lng, radius_km=_DRIVER_SEARCH_RADIUS_KM
    )

    driver_count = len(nearby_drivers)

    # Nearest driver is first because the service returns drivers sorted by
    # distance ascending.
    if nearby_drivers:
        nearest_distance_km: float | None = nearby_drivers[0]["distance_km"]
        pickup_eta = _pickup_eta_minutes(nearest_distance_km)
    else:
        nearest_distance_km = None
        pickup_eta = _NO_DRIVER_FALLBACK_ETA_MINUTES

    # Trip duration: haversine distance from pickup to dropoff.
    trip_distance_km = haversine_km(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    trip_duration = _trip_duration_minutes(trip_distance_km)

    return ETAEstimateResponse(
        pickup_eta_minutes=pickup_eta,
        trip_duration_minutes=trip_duration,
        nearest_driver_distance_km=nearest_distance_km,
        available_driver_count=driver_count,
        confidence=_confidence(driver_count),
    )
