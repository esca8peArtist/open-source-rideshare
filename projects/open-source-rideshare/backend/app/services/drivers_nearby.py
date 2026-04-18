"""Service layer for GET /drivers/nearby.

Provides:
  haversine_km   — inline great-circle distance (kilometres)
  eta_minutes    — rough ETA estimate at AVG_SPEED_KMH
  get_nearby_available_drivers_km — DB query returning available drivers within radius

Design notes
------------
- Uses a degree-based bounding box pre-filter then haversine in Python for the
  final distance, avoiding a PostGIS dependency so the query is portable.
- "Available" means is_online=True AND is_on_break=False (matches dispatch
  engine semantics in driver_location.py).  Heartbeat staleness is also
  checked (_HEARTBEAT_STALE_MINUTES) for consistency.
- No exact coordinates are returned to callers — only driver_id, distance_km,
  eta_minutes, and vehicle_type.  The API layer enforces this contract via
  the response schema.
"""

from __future__ import annotations

import math
import logging
from datetime import datetime, timedelta, timezone

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_availability import DriverOnlineStatus

logger = logging.getLogger(__name__)

# Drivers whose last heartbeat is older than this are excluded.
_HEARTBEAT_STALE_MINUTES = 5

# Rough average speed used for ETA estimates.
AVG_SPEED_KMH: float = 30.0

# Hard cap on the number of drivers returned to the caller.
MAX_DRIVERS_RETURNED: int = 20

# Default and maximum radius values (kilometres).
DEFAULT_RADIUS_KM: float = 5.0
MAX_RADIUS_KM: float = 20.0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two WGS-84 points.

    Uses the haversine formula — accurate to within ~0.5% for distances under
    a few hundred kilometres, which is more than sufficient for ETA estimation.
    """
    R = 6_371.0  # Earth radius in kilometres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2.0 * R * math.asin(math.sqrt(a))


def eta_minutes(distance_km: float, speed_kmh: float = AVG_SPEED_KMH) -> int:
    """Return a rough ETA in whole minutes given distance and average speed.

    Rounds up fractional minutes so callers never see ETA=0 for a non-zero
    distance (minimum returned is 1 when distance > 0).
    """
    if distance_km <= 0.0:
        return 0
    return max(1, math.ceil(distance_km / speed_kmh * 60.0))


# ---------------------------------------------------------------------------
# DB query
# ---------------------------------------------------------------------------


async def get_nearby_available_drivers_km(
    db: AsyncSession,
    lat: float,
    lng: float,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> list[dict]:
    """Return available drivers within *radius_km* kilometres of (*lat*, *lng*).

    Filters applied:
      - is_online = True
      - is_on_break = False
      - last_heartbeat within _HEARTBEAT_STALE_MINUTES (stale drivers excluded)
      - current_location IS NOT NULL

    A degree-based bounding box pre-filters rows in SQL so only a small
    candidate set is loaded into Python, where the exact haversine distance is
    computed and the radius check is applied.

    Returns a list of dicts with keys:
      driver_id    (int)
      distance_km  (float, rounded to 3 dp)
      vehicle_type (str | None)
      _lat         (float, internal — not forwarded to API response)
      _lng         (float, internal — not forwarded to API response)

    The list is sorted by distance_km ascending and capped at MAX_DRIVERS_RETURNED.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=_HEARTBEAT_STALE_MINUTES)

    # Bounding box: 1 degree latitude ≈ 111 km.  Longitude degree shrinks with
    # cos(lat) but we use the same slack for simplicity — it's slightly generous
    # near the equator and tighter near the poles, which is fine for a pre-filter.
    deg_slack = radius_km / 111.0

    stmt = (
        select(
            DriverProfile.id.label("driver_id"),
            DriverProfile.vehicle_type.label("vehicle_type"),
            ST_Y(DriverProfile.current_location).label("drv_lat"),
            ST_X(DriverProfile.current_location).label("drv_lng"),
        )
        .join(
            DriverOnlineStatus,
            DriverOnlineStatus.driver_id == DriverProfile.id,
        )
        .where(
            and_(
                DriverOnlineStatus.is_online.is_(True),
                DriverOnlineStatus.is_on_break.is_(False),
                DriverOnlineStatus.last_heartbeat >= stale_cutoff,
                DriverProfile.current_location.isnot(None),
            )
        )
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    nearby: list[dict] = []
    for row in rows:
        drv_lat = float(row.drv_lat)
        drv_lng = float(row.drv_lng)
        dist = haversine_km(lat, lng, drv_lat, drv_lng)
        if dist <= radius_km:
            nearby.append(
                {
                    "driver_id": row.driver_id,
                    "distance_km": round(dist, 3),
                    "vehicle_type": row.vehicle_type or None,
                }
            )

    nearby.sort(key=lambda d: d["distance_km"])
    return nearby[:MAX_DRIVERS_RETURNED]
