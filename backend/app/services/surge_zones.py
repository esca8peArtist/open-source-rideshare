"""Surge pricing zone service.

Provides geo-lookup helpers (haversine, ray-casting) and CRUD operations for
admin-managed surge pricing zones. The primary entry point for pricing code is
``get_active_surge_multiplier``, which returns the highest applicable multiplier
for a given lat/lon coordinate at the current time.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.surge import SurgePricingZone


# ---------------------------------------------------------------------------
# Pure geo helpers — no external dependencies
# ---------------------------------------------------------------------------


def point_in_circle(
    lat: float,
    lon: float,
    center_lat: float,
    center_lon: float,
    radius_km: float,
) -> bool:
    """Return True if (lat, lon) lies within radius_km of the center point.

    Uses the Haversine formula for great-circle distance on a sphere.
    Accurate to within ~0.3% for the distances typical of surge zones.
    """
    earth_radius_km = 6371.0
    dlat = math.radians(lat - center_lat)
    dlon = math.radians(lon - center_lon)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(center_lat))
        * math.cos(math.radians(lat))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    distance_km = earth_radius_km * c
    return distance_km <= radius_km


def point_in_polygon(lat: float, lon: float, polygon: list[dict]) -> bool:
    """Return True if (lat, lon) is inside the polygon defined by a list of
    ``{"lat": ..., "lon": ...}`` dicts.

    Uses the ray-casting algorithm. Points on the boundary are considered inside.
    The polygon does NOT need to be explicitly closed (first == last).
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["lon"], polygon[i]["lat"]
        xj, yj = polygon[j]["lon"], polygon[j]["lat"]

        intersect = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        )
        if intersect:
            inside = not inside
        j = i

    return inside


def is_zone_active_now(zone: SurgePricingZone, now: datetime | None = None) -> bool:
    """Return True if the zone's time-of-day and day-of-week constraints are
    satisfied at *now* (defaults to current UTC time).

    A zone with no time or day constraints is always considered active
    (subject only to its ``is_active`` flag, checked by the caller).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Day-of-week filter (0=Mon … 6=Sun, matching Python's weekday())
    if zone.days_of_week:
        if now.weekday() not in zone.days_of_week:
            return False

    # Time-of-day filter
    if zone.start_time is not None and zone.end_time is not None:
        current_time = now.time().replace(tzinfo=None)
        start = zone.start_time
        end = zone.end_time

        if start <= end:
            # Same-day window, e.g. 07:00 – 09:00
            if not (start <= current_time < end):
                return False
        else:
            # Overnight window, e.g. 22:00 – 06:00
            if not (current_time >= start or current_time < end):
                return False

    return True


def _point_in_zone(lat: float, lon: float, zone: SurgePricingZone) -> bool:
    """Return True if (lat, lon) falls within the zone's geographic boundary.

    Polygon check takes precedence over circle check when both are defined.
    """
    if zone.polygon:
        return point_in_polygon(lat, lon, zone.polygon)
    if (
        zone.center_lat is not None
        and zone.center_lon is not None
        and zone.radius_km is not None
    ):
        return point_in_circle(lat, lon, zone.center_lat, zone.center_lon, zone.radius_km)
    return False


# ---------------------------------------------------------------------------
# Main pricing lookup
# ---------------------------------------------------------------------------


async def get_active_surge_multiplier(
    db: AsyncSession,
    lat: float,
    lon: float,
    now: datetime | None = None,
) -> float:
    """Return the highest surge multiplier applicable to (lat, lon) right now.

    Checks all active zones, applies time/day constraints, and returns the
    maximum multiplier. Returns 1.0 if no zone applies (no surge).
    """
    result = await db.execute(
        select(SurgePricingZone).where(SurgePricingZone.is_active.is_(True))
    )
    zones = list(result.scalars().all())

    best = 1.0
    for zone in zones:
        if not is_zone_active_now(zone, now):
            continue
        if _point_in_zone(lat, lon, zone):
            if zone.multiplier > best:
                best = zone.multiplier
    return best


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


async def create_zone(
    db: AsyncSession,
    name: str,
    multiplier: float,
    description: str | None = None,
    polygon: list[dict] | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_km: float | None = None,
    is_active: bool = True,
    start_time=None,
    end_time=None,
    days_of_week: list[int] | None = None,
) -> SurgePricingZone:
    """Create and persist a new surge pricing zone."""
    zone = SurgePricingZone(
        name=name,
        description=description,
        polygon=polygon,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
        multiplier=multiplier,
        is_active=is_active,
        start_time=start_time,
        end_time=end_time,
        days_of_week=days_of_week,
    )
    db.add(zone)
    await db.flush()
    await db.refresh(zone)
    return zone


async def get_zone(db: AsyncSession, zone_id: uuid.UUID) -> SurgePricingZone | None:
    """Fetch a single surge pricing zone by its UUID primary key."""
    result = await db.execute(
        select(SurgePricingZone).where(SurgePricingZone.id == zone_id)
    )
    return result.scalar_one_or_none()


async def list_zones(
    db: AsyncSession,
    active_only: bool = False,
) -> list[SurgePricingZone]:
    """Return all surge pricing zones, optionally filtering to active ones."""
    query = select(SurgePricingZone).order_by(SurgePricingZone.name)
    if active_only:
        query = query.where(SurgePricingZone.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_zone(
    db: AsyncSession,
    zone_id: uuid.UUID,
    **kwargs,
) -> SurgePricingZone | None:
    """Update a surge pricing zone. Only supplied kwargs are changed.

    Returns None if the zone does not exist.
    """
    zone = await get_zone(db, zone_id)
    if zone is None:
        return None

    allowed = {
        "name", "description", "polygon", "center_lat", "center_lon",
        "radius_km", "multiplier", "is_active", "start_time", "end_time",
        "days_of_week",
    }
    for key, value in kwargs.items():
        if key in allowed:
            setattr(zone, key, value)

    await db.flush()
    await db.refresh(zone)
    return zone


async def delete_zone(db: AsyncSession, zone_id: uuid.UUID) -> bool:
    """Hard-delete a surge pricing zone. Returns True if deleted, False if not found."""
    zone = await get_zone(db, zone_id)
    if zone is None:
        return False
    await db.delete(zone)
    await db.flush()
    return True


async def toggle_zone_active(
    db: AsyncSession, zone_id: uuid.UUID, is_active: bool
) -> SurgePricingZone | None:
    """Activate or deactivate a zone. Returns updated zone or None if not found."""
    return await update_zone(db, zone_id, is_active=is_active)
