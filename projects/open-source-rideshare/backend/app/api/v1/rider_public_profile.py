"""GET /riders/{rider_id}/public-profile — driver pre-acceptance endpoint.

Allows a driver to view a rider's public profile before accepting a ride
request.  Only the rider's rating average, completed ride count, and join
date are exposed — no PII.

Requires driver authentication.  Returns 404 for unknown, inactive, or
non-rider user IDs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.user import User
from app.schemas.rider_public_profile import RiderPublicProfile
from app.services.rider_public_profile import get_rider_public_profile

router = APIRouter(tags=["riders"])


@router.get(
    "/riders/{rider_id}/public-profile",
    response_model=RiderPublicProfile,
    summary="Get a rider's public profile (driver auth required)",
    description=(
        "Returns a rider's average rating, completed ride count, and join date. "
        "Intended for the driver's pre-acceptance screen. "
        "No PII (name, email, phone) is returned. "
        "Returns 404 for unknown or inactive rider IDs."
    ),
)
async def get_public_profile(
    rider_id: int,
    driver: User = Depends(require_driver),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> RiderPublicProfile:
    """Return public profile for rider *rider_id*.

    Driver authentication is required — riders are not permitted to look
    up other riders' profiles.

    404 is returned for unknown riders, inactive accounts, and non-rider
    user IDs to prevent user enumeration.
    """
    profile = await get_rider_public_profile(db, rider_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rider {rider_id} not found",
        )
    return profile
