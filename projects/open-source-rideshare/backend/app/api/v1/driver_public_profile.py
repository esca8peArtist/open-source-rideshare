"""GET /drivers/{driver_id}/public-profile — rider pre-booking endpoint.

Returns non-PII driver information that a rider sees before confirming a
booking.  No authentication required — same model as /drivers/nearby and
/surge/current.

Only approved drivers are visible; unapproved drivers return 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.driver_public_profile import DriverPublicProfile
from app.services.driver_public_profile import get_driver_public_profile

router = APIRouter(tags=["drivers"])


@router.get(
    "/drivers/{driver_id}/public-profile",
    response_model=DriverPublicProfile,
    summary="Get a driver's public profile (no auth required)",
    description=(
        "Returns vehicle details, average rating, and trip count for an approved driver. "
        "Intended for the pre-booking confirmation screen. "
        "Unapproved drivers and non-existent driver IDs return 404. "
        "No authentication is required. "
        "PII (name, plate, license, insurance) is never returned."
    ),
)
async def get_public_profile(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
) -> DriverPublicProfile:
    """Return public profile for driver *driver_id*.

    404 is returned for:
    - Non-existent driver IDs
    - Drivers who have not been approved by the platform
    """
    profile = await get_driver_public_profile(db, driver_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Driver {driver_id} not found or not approved",
        )
    return profile
