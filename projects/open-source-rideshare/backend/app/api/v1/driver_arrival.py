"""Driver arrival countdown endpoint.

GET /rides/{ride_id}/driver-arrival

Rider-facing endpoint: returns real-time ETA and distance while a driver is
en route to the pickup point.  Accessible to the rider who owns the ride or
any admin.  Drivers are not permitted (they use the navigation endpoints).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User, UserRole
from app.schemas.driver_arrival import DriverArrivalResponse
from app.services.driver_arrival import get_driver_arrival

router = APIRouter(tags=["driver-arrival"])


@router.get(
    "/rides/{ride_id}/driver-arrival",
    response_model=DriverArrivalResponse,
    summary="Get driver arrival ETA and distance for a ride",
)
async def get_ride_driver_arrival(
    ride_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverArrivalResponse:
    """Return the driver's current distance and ETA to the pickup point.

    Accessible to the rider who booked the ride and platform admins.
    Drivers should use ``GET /rides/{ride_id}/navigation`` instead.

    The response is meaningful at any ride status, but distance and ETA are
    only populated while the driver has submitted a GPS fix.  Once the rider
    has been picked up (status ``arrived`` or later) the message field
    reflects the current ride status instead.

    Returns 404 if the ride does not exist or the caller does not own it.
    """
    # Drivers are not the intended audience — send them to the navigation endpoint.
    if current_user.role == UserRole.DRIVER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Drivers should use GET /rides/{ride_id}/navigation",
        )

    is_admin = current_user.role == UserRole.ADMIN

    try:
        return await get_driver_arrival(
            ride_id=ride_id,
            caller_id=current_user.id,
            caller_is_admin=is_admin,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
