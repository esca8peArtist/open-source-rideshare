"""Live-status polling endpoint.

GET /api/v1/rides/{ride_id}/live-status

Returns a compact, consolidated snapshot of the current ride state designed
for frequent polling (every 3–10 seconds) by the frontend.

Accessible to:
  - The rider who booked the ride
  - The driver assigned to the ride
  - Platform admins

All unauthorised callers receive 404 (not 403) to prevent ride-ID enumeration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User, UserRole
from app.schemas.ride_live_status import RideLiveStatus
from app.services.ride_live_status import get_ride_live_status

router = APIRouter(tags=["rides"])


@router.get(
    "/rides/{ride_id}/live-status",
    response_model=RideLiveStatus,
    summary="Get consolidated live status of a ride for frontend polling",
)
async def get_ride_live_status_endpoint(
    ride_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RideLiveStatus:
    """Return a compact state snapshot of the ride.

    Designed to be polled every 3–10 seconds by the frontend.  The
    ``poll_interval_seconds`` field in the response provides a recommended
    polling cadence based on the current ride status.

    Callers must be the rider who booked the ride, the driver assigned to
    it, or a platform admin.  All other callers receive 404 to prevent
    ride-ID enumeration.

    Raises 404 if the ride does not exist or the caller is not authorised.
    """
    is_driver = current_user.role == UserRole.DRIVER
    is_admin = current_user.role == UserRole.ADMIN

    try:
        return await get_ride_live_status(
            ride_id=ride_id,
            caller_id=current_user.id,
            caller_is_driver=is_driver,
            caller_is_admin=is_admin,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
