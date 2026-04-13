"""Driver destination filter API endpoints.

Driver-facing:
  PUT    /drivers/me/destination-filter  — set or update destination filter
  GET    /drivers/me/destination-filter  — get current destination filter
  DELETE /drivers/me/destination-filter  — clear (deactivate) destination filter

All endpoints require driver authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.driver_destination import (
    DriverDestinationFilterResponse,
    DriverDestinationFilterSet,
)
from app.services.driver_destination import (
    clear_destination_filter,
    get_destination_filter,
    set_destination_filter,
)

router = APIRouter(prefix="/drivers/me/destination-filter", tags=["driver-destination-filter"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _resolve_driver_id(user: User, db: AsyncSession) -> int:
    """Resolve the DriverProfile.id for the authenticated driver user."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        )
    return profile.id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.put(
    "",
    response_model=DriverDestinationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Set or update destination filter",
)
async def set_my_destination_filter(
    body: DriverDestinationFilterSet,
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Activate or update the driver's destination filter.

    When a destination filter is active, the matching engine only offers this
    driver rides whose dropoff point is within ``radius_km`` of the specified
    destination. Setting the filter again replaces any existing one.

    Pass ``expires_at`` to auto-deactivate at a specific UTC time (e.g. end of
    shift). Omit for no automatic expiry.
    """
    driver_id = await _resolve_driver_id(current_user, db)
    f = await set_destination_filter(
        db=db,
        driver_id=driver_id,
        destination_lat=body.destination_lat,
        destination_lon=body.destination_lon,
        radius_km=body.radius_km,
        expires_at=body.expires_at,
    )
    return DriverDestinationFilterResponse.from_filter(f)


@router.get(
    "",
    response_model=DriverDestinationFilterResponse,
    summary="Get current destination filter",
)
async def get_my_destination_filter(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver's current destination filter.

    Returns 404 if no filter has ever been set, or if the filter row has
    been cleared and there is no record to return.
    """
    driver_id = await _resolve_driver_id(current_user, db)
    f = await get_destination_filter(db=db, driver_id=driver_id)
    if f is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No destination filter set",
        )
    return DriverDestinationFilterResponse.from_filter(f)


@router.delete(
    "",
    response_model=DriverDestinationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear destination filter",
)
async def clear_my_destination_filter(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the driver's destination filter.

    After this call the driver will receive all eligible nearby ride requests
    again. Returns 404 if no filter has been set, 400 if already inactive.
    """
    driver_id = await _resolve_driver_id(current_user, db)
    f = await clear_destination_filter(db=db, driver_id=driver_id)
    return DriverDestinationFilterResponse.from_filter(f)
