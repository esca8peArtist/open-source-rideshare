"""GET /drivers/nearby — public pre-booking endpoint.

Lets a rider see how many available drivers are near their location before
committing to a booking request.  Requires no authentication (same pattern
as GET /surge/current).

Endpoint
--------
GET /drivers/nearby?lat={lat}&lng={lng}&radius_km={radius_km}

Parameters
----------
lat        required float  Rider's latitude  (-90 to 90)
lng        required float  Rider's longitude (-180 to 180)
radius_km  optional float  Search radius in km; default 5.0, max 20.0

Response
--------
{
  "drivers": [
    {
      "driver_id": int,
      "eta_minutes": int,
      "distance_km": float,
      "vehicle_type": str | null
    }
  ],
  "count": int,
  "radius_km": float
}

Privacy guarantees
------------------
- Exact driver coordinates are never returned.
- Driver names and any other PII are not included.
- Only distance_km and a rough ETA (distance / 30 km/h) are exposed.

Availability semantics
----------------------
Only drivers with is_online=True and is_on_break=False and a fresh heartbeat
(<= 5 minutes old) are returned — matching the dispatch engine's definition
of "available".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.drivers_nearby import DriversNearbyResponse, NearbyDriverEntry
from app.services.drivers_nearby import (
    DEFAULT_RADIUS_KM,
    MAX_DRIVERS_RETURNED,
    MAX_RADIUS_KM,
    eta_minutes,
    get_nearby_available_drivers_km,
)

router = APIRouter(tags=["drivers"])


@router.get(
    "/drivers/nearby",
    response_model=DriversNearbyResponse,
    summary="Get available drivers near a location (no auth required)",
    description=(
        "Returns up to 20 available drivers within the requested radius. "
        "No authentication is required — riders call this before entering a destination. "
        "Response includes distance and rough ETA only; exact driver coordinates and PII "
        "are never exposed. "
        "Drivers on break or with a stale heartbeat (>5 min) are excluded."
    ),
)
async def get_drivers_nearby(
    lat: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description="Rider's current latitude (-90 to 90)",
    ),
    lng: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description="Rider's current longitude (-180 to 180)",
    ),
    radius_km: float = Query(
        DEFAULT_RADIUS_KM,
        gt=0.0,
        le=MAX_RADIUS_KM,
        description=f"Search radius in kilometres (0 < radius_km <= {MAX_RADIUS_KM}; default {DEFAULT_RADIUS_KM})",
    ),
    db: AsyncSession = Depends(get_db),
) -> DriversNearbyResponse:
    """Return available drivers near the rider's location.

    Results are sorted by distance ascending and capped at
    {MAX_DRIVERS_RETURNED} drivers.  An empty list is returned (not 404) when
    no drivers are found within the radius.
    """.format(MAX_DRIVERS_RETURNED=MAX_DRIVERS_RETURNED)
    raw = await get_nearby_available_drivers_km(db, lat, lng, radius_km)

    entries = [
        NearbyDriverEntry(
            driver_id=d["driver_id"],
            distance_km=d["distance_km"],
            eta_minutes=eta_minutes(d["distance_km"]),
            vehicle_type=d["vehicle_type"],
        )
        for d in raw
    ]

    return DriversNearbyResponse(
        drivers=entries,
        count=len(entries),
        radius_km=radius_km,
    )
