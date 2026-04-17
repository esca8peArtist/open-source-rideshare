"""Driver live location update API.

Driver-facing:
  PUT /drivers/me/location              — submit current GPS position (DB + Redis)
  GET /drivers/me/location              — get own stored location

Rider-facing:
  GET /riders/nearby-drivers            — see available drivers nearby (fuzzy positions)

Admin-facing:
  GET /admin/drivers/locations          — all online drivers with exact positions
  GET /admin/drivers/{driver_id}/location — single driver's exact position
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin, require_driver
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.driver_location import (
    AdminDriverLocationItem,
    AdminDriverLocationsResponse,
    DriverLocationResponse,
    LocationUpdateRequest,
    NearbyDriverItem,
    NearbyDriversResponse,
)
from app.services.driver_location import (
    DEFAULT_RADIUS_M,
    MAX_NEARBY_LIMIT,
    MAX_RADIUS_M,
    MIN_RADIUS_M,
    fuzz_coordinate,
    get_all_online_driver_locations,
    get_driver_location_db,
    get_nearby_available_drivers,
    get_single_driver_location_admin,
    haversine_m,
    update_driver_location_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-location"])


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


async def _resolve_driver_profile_id(db: AsyncSession, user: User) -> int:
    """Return the DriverProfile.id for the authenticated driver, or raise 404."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )
    return profile.id


# ---------------------------------------------------------------------------
# Driver self-service endpoints
# ---------------------------------------------------------------------------


@router.put(
    "/drivers/me/location",
    response_model=DriverLocationResponse,
    summary="Update own current GPS location",
)
async def update_my_location(
    req: LocationUpdateRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated driver's current GPS position.

    Persists to ``driver_profiles.current_location`` (PostGIS POINT, SRID 4326)
    and pushes the new position into the Redis geo index used by the dispatch
    engine.

    This endpoint supplements the WebSocket ``location_update`` message —
    use the WebSocket path for high-frequency updates during an active trip and
    this REST endpoint for coarser periodic updates (e.g. when the app is in
    the background).
    """
    driver_id = await _resolve_driver_profile_id(db, user)

    try:
        await update_driver_location_db(db, driver_id, req.lat, req.lng)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    # Best-effort Redis update — failure here must not block the DB commit.
    try:
        from app.services.matching import get_matching_engine

        engine = await get_matching_engine()
        await engine.update_driver_location(user.id, req.lat, req.lng)
    except Exception:
        logger.warning(
            "Redis location update failed for driver %d (user %d) — DB persisted",
            driver_id,
            user.id,
        )

    return DriverLocationResponse(
        lat=req.lat,
        lng=req.lng,
        updated_at=datetime.now(timezone.utc),
    )


@router.get(
    "/drivers/me/location",
    response_model=DriverLocationResponse,
    summary="Get own stored location",
)
async def get_my_location(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver's last-known stored location from the database."""
    driver_id = await _resolve_driver_profile_id(db, user)
    lat, lng, updated_at = await get_driver_location_db(db, driver_id)
    return DriverLocationResponse(lat=lat, lng=lng, updated_at=updated_at)


# ---------------------------------------------------------------------------
# Rider endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/riders/nearby-drivers",
    response_model=NearbyDriversResponse,
    summary="Get nearby available drivers (privacy-safe)",
)
async def get_nearby_drivers(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Rider's current latitude"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Rider's current longitude"),
    radius_m: float = Query(
        DEFAULT_RADIUS_M,
        ge=MIN_RADIUS_M,
        le=MAX_RADIUS_M,
        description=f"Search radius in metres ({MIN_RADIUS_M}–{MAX_RADIUS_M})",
    ),
    limit: int = Query(
        MAX_NEARBY_LIMIT,
        ge=1,
        le=MAX_NEARBY_LIMIT,
        description=f"Maximum number of drivers to return (1–{MAX_NEARBY_LIMIT})",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return nearby available drivers for the rider's current position.

    Privacy guarantees:
    - Coordinates are rounded to 3 decimal places (~110 m precision).
    - No driver IDs or personal information are included.
    - Only online, not-on-break, heartbeat-fresh drivers are returned.

    Riders can use this to display driver pins on the pre-booking map.
    """
    raw = await get_nearby_available_drivers(db, lat, lng, radius_m, limit)

    drivers = [
        NearbyDriverItem(
            lat=fuzz_coordinate(d["lat"]),
            lng=fuzz_coordinate(d["lng"]),
            distance_m=round(haversine_m(lat, lng, d["lat"], d["lng"]), 1),
        )
        for d in raw
    ]

    return NearbyDriversResponse(
        drivers=drivers,
        total=len(drivers),
        as_of=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/locations",
    response_model=AdminDriverLocationsResponse,
    summary="List all online drivers with exact positions (admin only)",
)
async def admin_list_driver_locations(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return exact current locations for all online drivers.

    Includes drivers on break.  Drivers who have never submitted a location
    will appear with null lat/lng.
    """
    rows = await get_all_online_driver_locations(db)
    items = [
        AdminDriverLocationItem(
            driver_id=r["driver_id"],
            lat=r["lat"],
            lng=r["lng"],
            is_online=r["is_online"],
            is_on_break=r["is_on_break"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]
    return AdminDriverLocationsResponse(
        drivers=items,
        total=len(items),
        as_of=datetime.now(timezone.utc),
    )


@router.get(
    "/admin/drivers/{driver_id}/location",
    response_model=AdminDriverLocationItem,
    summary="Get a single driver's exact position (admin only)",
)
async def admin_get_driver_location(
    driver_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the exact current location for one driver."""
    row = await get_single_driver_location_admin(db, driver_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Driver profile {driver_id} not found.",
        )
    return AdminDriverLocationItem(
        driver_id=row["driver_id"],
        lat=row["lat"],
        lng=row["lng"],
        is_online=row["is_online"],
        is_on_break=row["is_on_break"],
        updated_at=row["updated_at"],
    )
