"""Service layer for driver live location updates.

Provides:
  update_driver_location_db — persist lat/lng to driver_profiles.current_location
  get_driver_location_db    — fetch driver's stored location from DB
  get_nearby_available_drivers — query nearby online (not-on-break) drivers via PostGIS
  get_all_online_driver_locations — admin view of all online drivers with coordinates
  fuzz_coordinate           — privacy helper: round to N decimal places

All functions that touch the DB are async and accept an AsyncSession.
The fuzz_coordinate helper is a pure function — no side effects, easy to test.

Geometry encoding
-----------------
PostgreSQL/PostGIS stores locations as WKB.  We use geoalchemy2.functions
(ST_X, ST_Y, ST_MakePoint, ST_DWithin) via SQLAlchemy so all geometry
handling stays in SQL — no WKB parsing in Python code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_X, ST_Y
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_availability import DriverOnlineStatus

logger = logging.getLogger(__name__)

# Drivers whose last heartbeat is older than this are excluded from nearby results.
_HEARTBEAT_STALE_MINUTES = 5

# Default fuzzing precision for rider-facing coordinates (3 dp ≈ 110 m).
_FUZZ_DECIMAL_PLACES = 3

# Default search radius in metres.
DEFAULT_RADIUS_M = 3_000
MAX_RADIUS_M = 10_000
MIN_RADIUS_M = 100

# Maximum drivers returned to rider (map display cap).
MAX_NEARBY_LIMIT = 50


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def fuzz_coordinate(coord: float, decimal_places: int = _FUZZ_DECIMAL_PLACES) -> float:
    """Round *coord* to *decimal_places* decimal places for privacy masking.

    At 3 decimal places the cell size is approximately:
      latitude:  ±0.00005° ≈ ±5.5 m
      longitude: ±0.00005° × cos(lat) — roughly ±3–6 m at typical latitudes

    This is tight enough to show a nearby pin on a map but loose enough that
    a rider cannot track a specific driver to their home address.
    """
    return round(coord, decimal_places)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres between two WGS-84 points.

    Used only for test helpers and fallback distance annotation; the primary
    distance filter uses PostGIS ST_DWithin.
    """
    import math

    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def update_driver_location_db(
    db: AsyncSession,
    driver_id: int,
    lat: float,
    lng: float,
) -> DriverProfile:
    """Persist a new location for *driver_id* in driver_profiles.

    Updates ``current_location`` (PostGIS POINT geometry, SRID 4326).
    The model's ``updated_at`` is refreshed automatically via the column
    ``onupdate`` trigger.

    Raises
    ------
    ValueError
        If no DriverProfile row exists for *driver_id*.
    """
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"Driver profile {driver_id} not found")

    profile.current_location = ST_MakePoint(lng, lat, 4326)
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_driver_location_db(
    db: AsyncSession,
    driver_id: int,
) -> tuple[float | None, float | None, datetime | None]:
    """Return (lat, lng, updated_at) for *driver_id*.

    lat/lng are None when the driver has never submitted a location.
    updated_at is the profile's last-modified timestamp (proxy for last
    location update).

    Uses ST_Y/ST_X to extract coordinates from the PostGIS POINT in SQL.
    """
    result = await db.execute(
        select(
            ST_Y(DriverProfile.current_location).label("lat"),
            ST_X(DriverProfile.current_location).label("lng"),
            DriverProfile.updated_at,
        ).where(DriverProfile.id == driver_id)
    )
    row = result.one_or_none()
    if row is None:
        return None, None, None
    lat = float(row.lat) if row.lat is not None else None
    lng = float(row.lng) if row.lng is not None else None
    return lat, lng, row.updated_at


async def get_nearby_available_drivers(
    db: AsyncSession,
    lat: float,
    lng: float,
    radius_m: float = DEFAULT_RADIUS_M,
    limit: int = MAX_NEARBY_LIMIT,
) -> list[dict]:
    """Return nearby online (not-on-break, heartbeat-fresh) drivers.

    Joins driver_profiles ↔ driver_online_status and filters:
      - is_online = True
      - is_on_break = False
      - last_heartbeat within _HEARTBEAT_STALE_MINUTES
      - current_location IS NOT NULL
      - ST_DWithin(current_location::geography, query_point::geography, radius_m)

    Returns a list of dicts with keys: lat, lng, driver_id (for internal use
    only — the API layer strips driver_id before returning to riders).
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=_HEARTBEAT_STALE_MINUTES)
    query_point = ST_MakePoint(lng, lat, 4326)

    stmt = (
        select(
            DriverProfile.id.label("driver_id"),
            ST_Y(DriverProfile.current_location).label("lat"),
            ST_X(DriverProfile.current_location).label("lng"),
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
                func.ST_DWithin(
                    func.ST_Transform(DriverProfile.current_location, 4326),
                    func.ST_Transform(query_point, 4326),
                    radius_m / 111_320.0,  # metres → approximate degrees
                ),
            )
        )
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.fetchall()
    return [
        {
            "driver_id": row.driver_id,
            "lat": float(row.lat),
            "lng": float(row.lng),
        }
        for row in rows
    ]


async def get_all_online_driver_locations(
    db: AsyncSession,
) -> list[dict]:
    """Return all online drivers with their current stored location.

    Used by the admin endpoint.  Does not filter by heartbeat freshness so
    admins can see stale locations too.  Includes is_online and is_on_break.

    Returns dicts with: driver_id, lat, lng, is_online, is_on_break,
    updated_at.
    """
    stmt = (
        select(
            DriverProfile.id.label("driver_id"),
            ST_Y(DriverProfile.current_location).label("lat"),
            ST_X(DriverProfile.current_location).label("lng"),
            DriverProfile.updated_at,
            DriverOnlineStatus.is_online,
            DriverOnlineStatus.is_on_break,
        )
        .join(
            DriverOnlineStatus,
            DriverOnlineStatus.driver_id == DriverProfile.id,
            isouter=True,
        )
        .where(DriverOnlineStatus.is_online.is_(True))
    )

    result = await db.execute(stmt)
    rows = result.fetchall()
    return [
        {
            "driver_id": row.driver_id,
            "lat": float(row.lat) if row.lat is not None else None,
            "lng": float(row.lng) if row.lng is not None else None,
            "is_online": bool(row.is_online),
            "is_on_break": bool(row.is_on_break),
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


async def get_single_driver_location_admin(
    db: AsyncSession,
    driver_id: int,
) -> dict | None:
    """Return location info for one driver (admin view).

    Returns None if no DriverProfile with that id exists.
    """
    result = await db.execute(
        select(
            DriverProfile.id.label("driver_id"),
            ST_Y(DriverProfile.current_location).label("lat"),
            ST_X(DriverProfile.current_location).label("lng"),
            DriverProfile.updated_at,
            DriverOnlineStatus.is_online,
            DriverOnlineStatus.is_on_break,
        )
        .join(
            DriverOnlineStatus,
            DriverOnlineStatus.driver_id == DriverProfile.id,
            isouter=True,
        )
        .where(DriverProfile.id == driver_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return {
        "driver_id": row.driver_id,
        "lat": float(row.lat) if row.lat is not None else None,
        "lng": float(row.lng) if row.lng is not None else None,
        "is_online": bool(row.is_online) if row.is_online is not None else False,
        "is_on_break": bool(row.is_on_break) if row.is_on_break is not None else False,
        "updated_at": row.updated_at,
    }
