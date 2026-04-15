"""Driver live location tracking endpoints.

Drivers broadcast their GPS position while on shift; riders can track the
assigned driver during an active ride; admins see all active drivers.

Endpoints
---------
POST  /drivers/me/location
    Driver pushes current GPS coordinates (upserts their location record).

GET   /rides/{ride_id}/driver-location
    Rider or driver fetches the current position of the driver on an
    active (en_route / arrived / in_progress) ride.

GET   /admin/drivers/live
    Admin-only: paginated list of all currently-active drivers and their
    last-known position.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_location import (
    ActiveDriverEntry,
    ActiveDriversResponse,
    DriverLocationResponse,
    LocationUpdate,
)
from app.services.driver_location import (
    get_ride_driver_location,
    list_active_drivers,
    upsert_driver_location,
)

router = APIRouter(tags=["driver-location"])


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/location",
    response_model=DriverLocationResponse,
    status_code=status.HTTP_200_OK,
    summary="Push driver GPS location",
)
async def push_driver_location(
    payload: LocationUpdate,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverLocationResponse:
    """Driver posts their current GPS coordinates.

    Call this endpoint at regular intervals (e.g., every 5–10 seconds)
    while on shift.  The platform upserts a single row per driver so
    storage overhead is constant.

    Optional ``ride_id`` links the update to a specific ride — useful for
    the rider-facing tracking endpoint.  If omitted, any previously stored
    ``ride_id`` is preserved.
    """
    loc = await upsert_driver_location(db, driver.id, payload)
    return DriverLocationResponse.from_orm_model(loc)


# ---------------------------------------------------------------------------
# Rider / driver — ride-scoped tracking
# ---------------------------------------------------------------------------


@router.get(
    "/rides/{ride_id}/driver-location",
    response_model=DriverLocationResponse,
    summary="Get driver's live location for an active ride",
)
async def get_driver_location_for_ride(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverLocationResponse:
    """Return the driver's current GPS position for an active ride.

    Available only while the ride is in ``driver_en_route``, ``arrived``,
    or ``in_progress`` status.  Both the rider and the driver on the ride
    may call this endpoint.

    Returns 404 if the driver has not yet broadcast a location update.
    Returns 409 if the ride is not in a trackable status.
    Returns 403 if the caller is not a participant in the ride.
    """
    loc = await get_ride_driver_location(db, ride_id, user.id)
    return DriverLocationResponse.from_orm_model(loc)


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/live",
    response_model=ActiveDriversResponse,
    summary="Admin: list all active drivers with their last-known position",
)
async def admin_list_live_drivers(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActiveDriversResponse:
    """Admin-only: paginated list of drivers currently broadcasting location.

    Useful for dispatch, operations monitoring, and safety audits.
    Returns drivers ordered by most-recently-updated first.
    """
    locations, total = await list_active_drivers(db, limit=limit, offset=offset)

    entries: list[ActiveDriverEntry] = []
    for loc in locations:
        driver_name: Optional[str] = None
        if loc.driver is not None:
            driver_name = getattr(loc.driver, "name", None) or getattr(
                loc.driver, "full_name", None
            )
        entries.append(
            ActiveDriverEntry(
                driver_id=loc.driver_id,
                driver_name=driver_name,
                ride_id=loc.ride_id,
                latitude=loc.latitude,
                longitude=loc.longitude,
                accuracy_meters=loc.accuracy_meters,
                heading=loc.heading,
                speed_kmh=loc.speed_kmh,
                updated_at=loc.updated_at,
            )
        )

    return ActiveDriversResponse(drivers=entries, total=total)
