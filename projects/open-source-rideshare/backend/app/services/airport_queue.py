"""Airport queue management service.

Provides:
  create_zone          — admin: create a new airport staging zone
  get_zone             — fetch a zone by id
  list_zones           — list all zones (optionally filter by airport_code)
  update_zone          — admin: update zone config
  get_zone_queue_size  — count of currently waiting drivers

  join_queue           — driver joins the waiting queue for a zone
  leave_queue          — driver leaves (self-removes) before dispatch
  get_my_entry         — driver fetches their own entry for a zone
  get_my_active_entries — driver fetches all zones they are currently waiting in
  get_position         — 1-based queue position for a driver in a zone

  dispatch_next        — admin/system: dispatch the front-of-queue driver
  remove_entry         — admin: forcibly remove any entry
  expire_stale         — system: mark ttl-exceeded waiting entries as expired
  admin_zone_view      — admin: full queue snapshot + today's stats
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airport_queue import AirportQueueEntry, AirportZone, QueueEntryStatus
from app.schemas.airport_queue import (
    AdminQueueView,
    AirportZoneCreate,
    AirportZoneResponse,
    AirportZoneUpdate,
    DispatchResponse,
    QueueEntryResponse,
    QueuePositionResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _zone_to_response(zone: AirportZone, queue_size: int = 0) -> AirportZoneResponse:
    return AirportZoneResponse(
        id=zone.id,
        name=zone.name,
        airport_code=zone.airport_code,
        terminal=zone.terminal,
        address=zone.address,
        latitude=zone.latitude,
        longitude=zone.longitude,
        max_queue_size=zone.max_queue_size,
        ttl_minutes=zone.ttl_minutes,
        is_active=zone.is_active,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
        current_queue_size=queue_size,
    )


def _entry_to_response(entry: AirportQueueEntry, position: int) -> QueueEntryResponse:
    return QueueEntryResponse(
        id=entry.id,
        zone_id=entry.zone_id,
        driver_id=entry.driver_id,
        status=entry.status.value,
        position=position,
        joined_at=entry.joined_at,
        dispatched_at=entry.dispatched_at,
        left_at=entry.left_at,
        expires_at=entry.expires_at,
    )


# ---------------------------------------------------------------------------
# Zone management
# ---------------------------------------------------------------------------


async def create_zone(req: AirportZoneCreate, db: AsyncSession) -> AirportZoneResponse:
    zone = AirportZone(
        name=req.name,
        airport_code=req.airport_code.upper(),
        terminal=req.terminal,
        address=req.address,
        latitude=req.latitude,
        longitude=req.longitude,
        max_queue_size=req.max_queue_size,
        ttl_minutes=req.ttl_minutes,
        is_active=True,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return _zone_to_response(zone, queue_size=0)


async def get_zone(zone_id: int, db: AsyncSession) -> AirportZone | None:
    result = await db.execute(select(AirportZone).where(AirportZone.id == zone_id))
    return result.scalar_one_or_none()


async def list_zones(
    airport_code: str | None,
    active_only: bool,
    db: AsyncSession,
) -> list[AirportZoneResponse]:
    q = select(AirportZone)
    if airport_code:
        q = q.where(AirportZone.airport_code == airport_code.upper())
    if active_only:
        q = q.where(AirportZone.is_active.is_(True))
    q = q.order_by(AirportZone.airport_code, AirportZone.name)

    zones = (await db.execute(q)).scalars().all()

    results: list[AirportZoneResponse] = []
    for zone in zones:
        size = await get_zone_queue_size(zone.id, db)
        results.append(_zone_to_response(zone, size))
    return results


async def update_zone(
    zone: AirportZone, req: AirportZoneUpdate, db: AsyncSession
) -> AirportZoneResponse:
    if req.name is not None:
        zone.name = req.name
    if req.terminal is not None:
        zone.terminal = req.terminal
    if req.address is not None:
        zone.address = req.address
    if req.latitude is not None:
        zone.latitude = req.latitude
    if req.longitude is not None:
        zone.longitude = req.longitude
    if req.max_queue_size is not None:
        zone.max_queue_size = req.max_queue_size
    if req.ttl_minutes is not None:
        zone.ttl_minutes = req.ttl_minutes
    if req.is_active is not None:
        zone.is_active = req.is_active

    await db.commit()
    await db.refresh(zone)
    size = await get_zone_queue_size(zone.id, db)
    return _zone_to_response(zone, size)


async def get_zone_queue_size(zone_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(AirportQueueEntry.id)).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
    )
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------


async def join_queue(
    driver_id: int, zone_id: int, db: AsyncSession
) -> QueueEntryResponse:
    """Add a driver to the waiting queue for a zone.

    Raises ValueError if:
      - zone not found or inactive
      - driver already in this zone's queue
      - queue is at capacity
    """
    zone_result = await db.execute(
        select(AirportZone).where(AirportZone.id == zone_id)
    )
    zone = zone_result.scalar_one_or_none()
    if not zone:
        raise ValueError("Airport zone not found")
    if not zone.is_active:
        raise ValueError("This airport zone is not currently accepting drivers")

    # Duplicate check
    existing = await db.execute(
        select(AirportQueueEntry).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.driver_id == driver_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("You are already in the queue for this zone")

    # Capacity check
    current_size = await get_zone_queue_size(zone_id, db)
    if current_size >= zone.max_queue_size:
        raise ValueError(
            f"Queue is full ({zone.max_queue_size} drivers). Try again later."
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=zone.ttl_minutes)

    entry = AirportQueueEntry(
        zone_id=zone_id,
        driver_id=driver_id,
        status=QueueEntryStatus.waiting,
        joined_at=now,
        expires_at=expires_at,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    position = await get_position(driver_id, zone_id, db)
    return _entry_to_response(entry, position or 1)


async def leave_queue(driver_id: int, zone_id: int, db: AsyncSession) -> None:
    """Driver self-removes from the queue before being dispatched."""
    entry_result = await db.execute(
        select(AirportQueueEntry).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.driver_id == driver_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if not entry:
        raise ValueError("No active queue entry found for this zone")

    entry.status = QueueEntryStatus.left
    entry.left_at = datetime.now(timezone.utc)
    await db.commit()


async def get_my_entry(
    driver_id: int, zone_id: int, db: AsyncSession
) -> QueueEntryResponse | None:
    """Get a driver's current waiting entry for a specific zone."""
    entry_result = await db.execute(
        select(AirportQueueEntry).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.driver_id == driver_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if not entry:
        return None
    position = await get_position(driver_id, zone_id, db)
    return _entry_to_response(entry, position or 1)


async def get_my_active_entries(
    driver_id: int, db: AsyncSession
) -> list[QueuePositionResponse]:
    """Get all zones the driver is currently waiting in."""
    entries_result = await db.execute(
        select(AirportQueueEntry, AirportZone)
        .join(AirportZone, AirportQueueEntry.zone_id == AirportZone.id)
        .where(
            AirportQueueEntry.driver_id == driver_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
        .order_by(AirportQueueEntry.joined_at)
    )
    rows = entries_result.all()

    responses = []
    for entry, zone in rows:
        position = await get_position(driver_id, zone.id, db)
        queue_depth = await get_zone_queue_size(zone.id, db)
        responses.append(
            QueuePositionResponse(
                zone_id=zone.id,
                zone_name=zone.name,
                airport_code=zone.airport_code,
                status=entry.status.value,
                position=position,
                queue_depth=queue_depth,
                joined_at=entry.joined_at,
                expires_at=entry.expires_at,
            )
        )
    return responses


async def get_position(driver_id: int, zone_id: int, db: AsyncSession) -> int | None:
    """Return the 1-based FIFO position of a driver in a zone's waiting queue.

    Returns None if the driver has no waiting entry in that zone.
    """
    # Get the driver's joined_at
    entry_result = await db.execute(
        select(AirportQueueEntry.joined_at).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.driver_id == driver_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
    )
    row = entry_result.first()
    if not row:
        return None

    driver_joined_at = row[0]

    # Count how many drivers joined before this driver
    count_result = await db.execute(
        select(func.count(AirportQueueEntry.id)).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
            AirportQueueEntry.joined_at < driver_joined_at,
        )
    )
    ahead = count_result.scalar() or 0
    return ahead + 1


async def dispatch_next(zone_id: int, db: AsyncSession) -> DispatchResponse:
    """Dispatch the front-of-queue (earliest joined_at) waiting driver.

    Returns a DispatchResponse including the id of the next driver in queue
    (if any) for informational purposes.
    """
    # Fetch the FIFO head
    head_result = await db.execute(
        select(AirportQueueEntry)
        .where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
        .order_by(AirportQueueEntry.joined_at.asc())
        .limit(1)
    )
    head = head_result.scalar_one_or_none()
    if not head:
        raise ValueError("Queue is empty — no driver to dispatch")

    now = datetime.now(timezone.utc)
    head.status = QueueEntryStatus.dispatched
    head.dispatched_at = now
    await db.commit()

    # Peek at next driver
    next_result = await db.execute(
        select(AirportQueueEntry.driver_id)
        .where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
        .order_by(AirportQueueEntry.joined_at.asc())
        .limit(1)
    )
    next_row = next_result.first()
    next_driver_id = next_row[0] if next_row else None

    return DispatchResponse(
        dispatched_entry_id=head.id,
        driver_id=head.driver_id,
        zone_id=zone_id,
        dispatched_at=now,
        next_in_queue=next_driver_id,
    )


async def remove_entry(entry_id: int, db: AsyncSession) -> None:
    """Admin forcibly removes any queue entry (any status)."""
    entry_result = await db.execute(
        select(AirportQueueEntry).where(AirportQueueEntry.id == entry_id)
    )
    entry = entry_result.scalar_one_or_none()
    if not entry:
        raise ValueError("Queue entry not found")
    if entry.status == QueueEntryStatus.waiting:
        entry.status = QueueEntryStatus.left
        entry.left_at = datetime.now(timezone.utc)
        await db.commit()


async def expire_stale(zone_id: int, db: AsyncSession) -> int:
    """Mark TTL-exceeded waiting entries as expired.

    Returns the number of entries expired.
    """
    now = datetime.now(timezone.utc)
    stale_result = await db.execute(
        select(AirportQueueEntry).where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
            AirportQueueEntry.expires_at <= now,
        )
    )
    stale = stale_result.scalars().all()
    for entry in stale:
        entry.status = QueueEntryStatus.expired
    if stale:
        await db.commit()
    return len(stale)


async def admin_zone_view(zone_id: int, db: AsyncSession) -> AdminQueueView:
    """Full snapshot of the live queue plus today's activity stats."""
    zone_result = await db.execute(
        select(AirportZone).where(AirportZone.id == zone_id)
    )
    zone = zone_result.scalar_one_or_none()
    if not zone:
        raise ValueError("Airport zone not found")

    # Expire stale entries first so view is accurate
    await expire_stale(zone_id, db)

    # Fetch ordered waiting queue
    waiting_result = await db.execute(
        select(AirportQueueEntry)
        .where(
            AirportQueueEntry.zone_id == zone_id,
            AirportQueueEntry.status == QueueEntryStatus.waiting,
        )
        .order_by(AirportQueueEntry.joined_at.asc())
    )
    waiting_entries = waiting_result.scalars().all()
    waiting_responses = [
        _entry_to_response(e, idx + 1) for idx, e in enumerate(waiting_entries)
    ]

    # Today's stats
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    dispatched_today = (
        await db.execute(
            select(func.count(AirportQueueEntry.id)).where(
                AirportQueueEntry.zone_id == zone_id,
                AirportQueueEntry.status == QueueEntryStatus.dispatched,
                AirportQueueEntry.dispatched_at >= today_start,
            )
        )
    ).scalar() or 0

    expired_today = (
        await db.execute(
            select(func.count(AirportQueueEntry.id)).where(
                AirportQueueEntry.zone_id == zone_id,
                AirportQueueEntry.status == QueueEntryStatus.expired,
                AirportQueueEntry.joined_at >= today_start,
            )
        )
    ).scalar() or 0

    zone_response = _zone_to_response(zone, len(waiting_entries))

    return AdminQueueView(
        zone=zone_response,
        waiting=waiting_responses,
        total_dispatched_today=int(dispatched_today),
        total_expired_today=int(expired_today),
    )
