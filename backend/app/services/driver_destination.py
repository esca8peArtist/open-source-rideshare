"""Driver destination filter service.

Drivers can activate a destination filter so the matching engine only offers
them rides whose dropoff is within a configurable radius of their chosen
destination. This is commonly called "going-home mode" on commercial rideshare
platforms.

Public interface
----------------
set_destination_filter      — create or update the filter for a driver
clear_destination_filter    — deactivate the filter without deleting the row
get_destination_filter      — fetch the filter row for a driver (or None)
get_active_filters_for_drivers
                            — bulk-fetch active filters; used by MatchingEngine
haversine_km                — great-circle distance helper (pure Python)
dropoff_within_filter       — True when a dropoff point satisfies a filter
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_destination import DriverDestinationFilter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geometry helpers (no extra dependencies needed)
# ---------------------------------------------------------------------------

_EARTH_RADIUS_KM = 6_371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in km between two lat/lon points."""
    lat1_r, lon1_r, lat2_r, lon2_r = (
        math.radians(lat1),
        math.radians(lon1),
        math.radians(lat2),
        math.radians(lon2),
    )
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def dropoff_within_filter(
    filter_row: DriverDestinationFilter,
    dropoff_lat: float,
    dropoff_lon: float,
) -> bool:
    """Return True when the dropoff point is within the filter's radius.

    Also checks that the filter is active and not expired.
    """
    now = datetime.now(timezone.utc)
    if not filter_row.is_active:
        return False
    if filter_row.expires_at is not None and filter_row.expires_at <= now:
        return False
    dist = haversine_km(
        filter_row.destination_lat,
        filter_row.destination_lon,
        dropoff_lat,
        dropoff_lon,
    )
    return dist <= filter_row.radius_km


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def set_destination_filter(
    db: AsyncSession,
    driver_id: int,
    destination_lat: float,
    destination_lon: float,
    radius_km: float = 5.0,
    expires_at: datetime | None = None,
) -> DriverDestinationFilter:
    """Create or replace the destination filter for a driver.

    If a row already exists for this driver it is updated in-place (upsert);
    otherwise a new row is inserted. The filter is set to ``is_active=True``.
    """
    result = await db.execute(
        select(DriverDestinationFilter).where(
            DriverDestinationFilter.driver_id == driver_id
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.destination_lat = destination_lat
        existing.destination_lon = destination_lon
        existing.radius_km = radius_km
        existing.expires_at = expires_at
        existing.is_active = True
        await db.flush()
        await db.refresh(existing)
        return existing

    new_filter = DriverDestinationFilter(
        driver_id=driver_id,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
        radius_km=radius_km,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(new_filter)
    await db.flush()
    await db.refresh(new_filter)
    return new_filter


async def clear_destination_filter(
    db: AsyncSession,
    driver_id: int,
) -> DriverDestinationFilter:
    """Deactivate the destination filter for a driver.

    Raises 404 if no filter row exists for this driver.
    Raises 400 if the filter is already inactive.
    """
    result = await db.execute(
        select(DriverDestinationFilter).where(
            DriverDestinationFilter.driver_id == driver_id
        )
    )
    f = result.scalar_one_or_none()

    if f is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No destination filter found for this driver",
        )

    if not f.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Destination filter is already inactive",
        )

    f.is_active = False
    await db.flush()
    return f


async def get_destination_filter(
    db: AsyncSession,
    driver_id: int,
) -> DriverDestinationFilter | None:
    """Return the destination filter row for a driver, or None if absent."""
    result = await db.execute(
        select(DriverDestinationFilter).where(
            DriverDestinationFilter.driver_id == driver_id
        )
    )
    return result.scalar_one_or_none()


async def get_active_filters_for_drivers(
    db: AsyncSession,
    driver_ids: list[int],
) -> dict[int, DriverDestinationFilter]:
    """Bulk-fetch currently-active destination filters for the given driver IDs.

    Returns a dict mapping driver_id → DriverDestinationFilter for drivers
    that have an active (and not-yet-expired) filter. Drivers with no active
    filter are absent from the dict.

    Used by the MatchingEngine to filter ride candidates by destination.
    """
    if not driver_ids:
        return {}

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(DriverDestinationFilter).where(
            DriverDestinationFilter.driver_id.in_(driver_ids),
            DriverDestinationFilter.is_active.is_(True),
        )
    )
    rows = result.scalars().all()

    active: dict[int, DriverDestinationFilter] = {}
    for row in rows:
        # Exclude expired filters
        if row.expires_at is not None and row.expires_at <= now:
            continue
        active[row.driver_id] = row

    return active
