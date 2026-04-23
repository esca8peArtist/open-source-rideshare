"""Driver in-ride navigation endpoints.

GET  /rides/{ride_id}/navigation          — driver fetches current navigation state
POST /rides/{ride_id}/navigation/position — driver reports GPS position, gets updated state
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.user import User
from app.schemas.driver_navigation import (
    NavigationPositionUpdate,
    NavigationStateResponse,
)
from app.services.driver_navigation import (
    get_navigation_state,
    update_navigation_position,
)

router = APIRouter(tags=["driver-navigation"])


@router.get(
    "/rides/{ride_id}/navigation",
    response_model=NavigationStateResponse,
    summary="Get navigation state for an active ride",
)
async def get_ride_navigation(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> NavigationStateResponse:
    """Return the ordered stop list with ETAs for the driver's current ride.

    Stops are ordered: pickup → waypoints (by position) → dropoff.
    Each pending stop includes distance and ETA from the driver's last known location.
    Call POST /navigation/position to submit a GPS update and get fresh distances.
    """
    try:
        return await get_navigation_state(ride_id=ride_id, driver_id=driver.id, db=db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/rides/{ride_id}/navigation/position",
    response_model=NavigationStateResponse,
    summary="Submit driver GPS position and get updated navigation state",
)
async def post_navigation_position(
    ride_id: int,
    body: NavigationPositionUpdate,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> NavigationStateResponse:
    """Report the driver's current GPS coordinates and receive an updated navigation state.

    Distances and ETAs for all pending stops are recalculated from the submitted position.
    If the driver is more than 500 m off the direct path between stops, a route deviation
    is flagged on the ride (admin-visible on the safety dashboard).  The flag is set only
    once — repeated off-route reports do not overwrite it.

    Only accepted while the ride is DRIVER_EN_ROUTE, ARRIVED, or IN_PROGRESS.
    """
    try:
        return await update_navigation_position(
            ride_id=ride_id,
            driver_id=driver.id,
            lat=body.lat,
            lng=body.lng,
            db=db,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
