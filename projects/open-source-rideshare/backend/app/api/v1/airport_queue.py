"""Airport queue management endpoints.

Driver endpoints (authenticated, DRIVER role):
  POST   /drivers/me/airport-queue/{zone_id}   — join the queue for a zone
  DELETE /drivers/me/airport-queue/{zone_id}   — leave the queue (self-remove)
  GET    /drivers/me/airport-queue/{zone_id}   — check own position in a zone
  GET    /drivers/me/airport-queue             — all zones driver is currently queued in

Admin endpoints (ADMIN role):
  POST   /admin/airport-zones                          — create a zone
  GET    /admin/airport-zones                          — list all zones
  GET    /admin/airport-zones/{zone_id}                — get zone details + live queue
  PUT    /admin/airport-zones/{zone_id}                — update zone config
  POST   /admin/airport-zones/{zone_id}/dispatch       — dispatch next driver
  DELETE /admin/airport-zones/{zone_id}/entries/{entry_id} — remove entry
  POST   /admin/airport-zones/{zone_id}/expire         — expire stale entries
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User, UserRole
from app.schemas.airport_queue import (
    AdminQueueView,
    AirportZoneCreate,
    AirportZoneResponse,
    AirportZoneUpdate,
    DispatchResponse,
    JoinQueueRequest,
    QueueEntryResponse,
    QueuePositionResponse,
)
from app.services import airport_queue as svc

router = APIRouter(tags=["airport_queue"])


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/airport-queue/{zone_id}",
    response_model=QueueEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_queue(
    zone_id: int,
    req: JoinQueueRequest = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Join the waiting queue for an airport zone.

    The driver is placed at the back of the FIFO queue.  A TTL is set
    based on the zone's ``ttl_minutes`` — the entry auto-expires if the
    driver has not been dispatched within that window.
    """
    if user.role != UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers may join airport queues")
    try:
        return await svc.join_queue(user.id, zone_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/drivers/me/airport-queue/{zone_id}",
    status_code=status.HTTP_200_OK,
)
async def leave_queue(
    zone_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Leave an airport queue before being dispatched."""
    if user.role != UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers may leave airport queues")
    try:
        await svc.leave_queue(user.id, zone_id, db)
        return {"status": "left", "zone_id": zone_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/drivers/me/airport-queue/{zone_id}",
    response_model=QueuePositionResponse,
)
async def get_queue_position(
    zone_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the driver's current queue position and status in a specific zone."""
    if user.role != UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers may view airport queue positions")

    entry = await svc.get_my_entry(user.id, zone_id, db)
    if not entry:
        raise HTTPException(status_code=404, detail="You are not in the queue for this zone")

    zone = await svc.get_zone(zone_id, db)
    queue_depth = await svc.get_zone_queue_size(zone_id, db)

    return QueuePositionResponse(
        zone_id=zone_id,
        zone_name=zone.name if zone else "",
        airport_code=zone.airport_code if zone else "",
        status=entry.status,
        position=entry.position,
        queue_depth=queue_depth,
        joined_at=entry.joined_at,
        expires_at=entry.expires_at,
    )


@router.get(
    "/drivers/me/airport-queue",
    response_model=list[QueuePositionResponse],
)
async def list_my_queue_entries(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all airport zones the driver is currently waiting in."""
    if user.role != UserRole.driver:
        raise HTTPException(status_code=403, detail="Only drivers may view airport queue positions")
    return await svc.get_my_active_entries(user.id, db)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/admin/airport-zones",
    response_model=AirportZoneResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_zone(
    req: AirportZoneCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new airport staging / pickup zone."""
    return await svc.create_zone(req, db)


@router.get(
    "/admin/airport-zones",
    response_model=list[AirportZoneResponse],
    dependencies=[Depends(require_admin)],
)
async def list_zones(
    airport_code: str | None = Query(None, description="Filter by IATA airport code"),
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """List all airport zones (optionally filtered by airport code)."""
    return await svc.list_zones(airport_code, active_only, db)


@router.get(
    "/admin/airport-zones/{zone_id}",
    response_model=AdminQueueView,
    dependencies=[Depends(require_admin)],
)
async def get_zone_view(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the full live queue snapshot for a zone, including today's stats."""
    try:
        return await svc.admin_zone_view(zone_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/admin/airport-zones/{zone_id}",
    response_model=AirportZoneResponse,
    dependencies=[Depends(require_admin)],
)
async def update_zone(
    zone_id: int,
    req: AirportZoneUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update zone configuration (capacity, TTL, active status, etc.)."""
    zone = await svc.get_zone(zone_id, db)
    if not zone:
        raise HTTPException(status_code=404, detail="Airport zone not found")
    return await svc.update_zone(zone, req, db)


@router.post(
    "/admin/airport-zones/{zone_id}/dispatch",
    response_model=DispatchResponse,
    dependencies=[Depends(require_admin)],
)
async def dispatch_next(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Dispatch the front-of-queue driver for a zone.

    Sets the first waiting entry to ``dispatched`` and returns the
    dispatched driver's id along with the next driver in line (if any).
    """
    zone = await svc.get_zone(zone_id, db)
    if not zone:
        raise HTTPException(status_code=404, detail="Airport zone not found")
    try:
        return await svc.dispatch_next(zone_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/admin/airport-zones/{zone_id}/entries/{entry_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def remove_entry(
    zone_id: int,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Forcibly remove a driver's queue entry (admin action)."""
    try:
        await svc.remove_entry(entry_id, db)
        return {"status": "removed", "entry_id": entry_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/admin/airport-zones/{zone_id}/expire",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def expire_stale(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Expire any waiting entries that have exceeded their TTL.

    The admin_zone_view endpoint calls this automatically, but this
    endpoint allows manual triggering (e.g., by a scheduled job).
    """
    zone = await svc.get_zone(zone_id, db)
    if not zone:
        raise HTTPException(status_code=404, detail="Airport zone not found")
    count = await svc.expire_stale(zone_id, db)
    return {"expired_count": count, "zone_id": zone_id}
