from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_driver
from app.db.database import get_db
from app.models.user import User
from app.models.waypoint import WaypointStatus
from app.schemas.waypoint import (
    WaypointCreate,
    WaypointListResponse,
    WaypointResponse,
    WaypointUpdate,
)
from app.services.waypoints import (
    WaypointError,
    add_waypoint,
    get_waypoints,
    remove_waypoint,
    update_waypoint,
    update_waypoint_status,
)

router = APIRouter(prefix="/rides/{ride_id}/waypoints", tags=["waypoints"])


@router.get("", response_model=WaypointListResponse)
async def list_waypoints(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all waypoints for a ride, ordered by position."""
    waypoints = await get_waypoints(db, ride_id)
    return WaypointListResponse(
        ride_id=ride_id,
        waypoints=[WaypointResponse.model_validate(wp) for wp in waypoints],
        total_waypoints=len(waypoints),
    )


@router.post("", response_model=WaypointResponse, status_code=status.HTTP_201_CREATED)
async def create_waypoint(
    ride_id: int,
    req: WaypointCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a waypoint to a ride. Rider only."""
    try:
        waypoint = await add_waypoint(
            db,
            ride_id=ride_id,
            user_id=user.id,
            address=req.address,
            lat=req.lat,
            lng=req.lng,
            wait_time_minutes=req.wait_time_minutes,
            notes=req.notes,
        )
    except WaypointError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "not authorized" in msg.lower():
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return WaypointResponse.model_validate(waypoint)


@router.patch("/{waypoint_id}", response_model=WaypointResponse)
async def modify_waypoint(
    ride_id: int,
    waypoint_id: int,
    req: WaypointUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a pending waypoint's details. Rider only."""
    update_data = req.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=422, detail="No fields to update")
    try:
        waypoint = await update_waypoint(db, ride_id, waypoint_id, user.id, update_data)
    except WaypointError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "not authorized" in msg.lower():
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return WaypointResponse.model_validate(waypoint)


@router.delete("/{waypoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_waypoint(
    ride_id: int,
    waypoint_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a pending waypoint. Rider only. Reorders remaining waypoints."""
    try:
        await remove_waypoint(db, ride_id, waypoint_id, user.id)
    except WaypointError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "not authorized" in msg.lower():
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=409, detail=msg)


@router.post(
    "/{waypoint_id}/arrive",
    response_model=WaypointResponse,
)
async def arrive_at_waypoint(
    ride_id: int,
    waypoint_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Mark a waypoint as arrived. Driver only."""
    try:
        waypoint = await update_waypoint_status(
            db, ride_id, waypoint_id, WaypointStatus.ARRIVED
        )
    except WaypointError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return WaypointResponse.model_validate(waypoint)


@router.post(
    "/{waypoint_id}/depart",
    response_model=WaypointResponse,
)
async def depart_from_waypoint(
    ride_id: int,
    waypoint_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Mark a waypoint as departed. Driver only."""
    try:
        waypoint = await update_waypoint_status(
            db, ride_id, waypoint_id, WaypointStatus.DEPARTED
        )
    except WaypointError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return WaypointResponse.model_validate(waypoint)


@router.post(
    "/{waypoint_id}/skip",
    response_model=WaypointResponse,
)
async def skip_waypoint(
    ride_id: int,
    waypoint_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Skip a waypoint. Available to both rider and driver."""
    try:
        waypoint = await update_waypoint_status(
            db, ride_id, waypoint_id, WaypointStatus.SKIPPED
        )
    except WaypointError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return WaypointResponse.model_validate(waypoint)
