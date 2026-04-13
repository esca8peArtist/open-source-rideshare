"""Service layer for driver availability and scheduling.

Provides:
  - Schedule CRUD: set_schedule_slot, delete_schedule_slot, get_driver_schedule
  - Online status: set_driver_online, get_online_drivers, update_heartbeat
  - Availability logic: is_driver_available_now, get_available_drivers_for_matching

All functions are async and accept an AsyncSession.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_availability import DriverOnlineStatus, DriverSchedule
from app.schemas.driver_availability import ScheduleSlotCreate

logger = logging.getLogger(__name__)

# A heartbeat older than this threshold means the driver is considered stale.
HEARTBEAT_STALE_MINUTES = 5


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------


async def set_schedule_slot(
    db: AsyncSession,
    driver_id: int,
    slot: ScheduleSlotCreate,
) -> DriverSchedule:
    """Upsert a weekly availability slot for a driver.

    If a slot already exists for the same (driver_id, day_of_week, start_time)
    combination it is updated in-place; otherwise a new row is created.

    Parameters
    ----------
    db:        Active async database session.
    driver_id: ID of the DriverProfile row.
    slot:      Validated ScheduleSlotCreate schema.

    Returns
    -------
    The created or updated DriverSchedule ORM object.
    """
    result = await db.execute(
        select(DriverSchedule).where(
            DriverSchedule.driver_id == driver_id,
            DriverSchedule.day_of_week == slot.day_of_week,
            DriverSchedule.start_time == slot.start_as_time(),
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.end_time = slot.end_as_time()
        existing.is_active = True
        await db.flush()
        return existing

    new_slot = DriverSchedule(
        driver_id=driver_id,
        day_of_week=slot.day_of_week,
        start_time=slot.start_as_time(),
        end_time=slot.end_as_time(),
        is_active=True,
    )
    db.add(new_slot)
    await db.flush()
    return new_slot


async def delete_schedule_slot(
    db: AsyncSession,
    driver_id: int,
    slot_id: int,
) -> bool:
    """Delete a schedule slot owned by driver_id.

    Returns True if the slot was found and deleted, False if not found
    (or if it belongs to a different driver).
    """
    result = await db.execute(
        select(DriverSchedule).where(
            DriverSchedule.id == slot_id,
            DriverSchedule.driver_id == driver_id,
        )
    )
    slot = result.scalar_one_or_none()
    if slot is None:
        return False
    await db.delete(slot)
    await db.flush()
    return True


async def get_driver_schedule(
    db: AsyncSession,
    driver_id: int,
) -> list[DriverSchedule]:
    """Return all active and inactive slots for a driver.

    Ordered by day_of_week ascending, then start_time ascending.
    """
    result = await db.execute(
        select(DriverSchedule)
        .where(DriverSchedule.driver_id == driver_id)
        .order_by(DriverSchedule.day_of_week, DriverSchedule.start_time)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Online status
# ---------------------------------------------------------------------------


async def set_driver_online(
    db: AsyncSession,
    driver_id: int,
    is_online: bool,
) -> DriverOnlineStatus:
    """Upsert the online/offline state for a driver.

    When transitioning *to* online, ``went_online_at`` is stamped with the
    current UTC time.  Transitioning to offline leaves ``went_online_at``
    unchanged so the duration can be calculated later.

    Parameters
    ----------
    db:        Active async database session.
    driver_id: ID of the DriverProfile row.
    is_online: Desired online state.

    Returns
    -------
    The upserted DriverOnlineStatus ORM object.
    """
    result = await db.execute(
        select(DriverOnlineStatus).where(DriverOnlineStatus.driver_id == driver_id)
    )
    status_row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if status_row is None:
        status_row = DriverOnlineStatus(
            driver_id=driver_id,
            is_online=is_online,
            went_online_at=now if is_online else None,
            last_heartbeat=now if is_online else None,
        )
        db.add(status_row)
    else:
        # Stamp went_online_at only on the transition from offline → online.
        if is_online and not status_row.is_online:
            status_row.went_online_at = now
            status_row.last_heartbeat = now
        status_row.is_online = is_online

    await db.flush()
    return status_row


async def get_online_drivers(db: AsyncSession) -> list[int]:
    """Return driver_ids of all drivers currently marked as online."""
    result = await db.execute(
        select(DriverOnlineStatus.driver_id).where(DriverOnlineStatus.is_online.is_(True))
    )
    return list(result.scalars().all())


async def update_heartbeat(
    db: AsyncSession,
    driver_id: int,
) -> DriverOnlineStatus:
    """Touch the last_heartbeat timestamp for a driver.

    This function only updates the timestamp — it does NOT auto-offline stale
    drivers.  Stale-heartbeat enforcement is intentionally separated so it can
    be run as a background task without coupling to the heartbeat endpoint.

    If no online-status row exists yet, one is created with is_online=True so
    that sending a heartbeat implicitly brings the driver online.
    """
    result = await db.execute(
        select(DriverOnlineStatus).where(DriverOnlineStatus.driver_id == driver_id)
    )
    status_row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if status_row is None:
        status_row = DriverOnlineStatus(
            driver_id=driver_id,
            is_online=True,
            went_online_at=now,
            last_heartbeat=now,
        )
        db.add(status_row)
    else:
        status_row.last_heartbeat = now

    await db.flush()
    return status_row


def _heartbeat_is_stale(last_heartbeat: datetime | None) -> bool:
    """Return True if last_heartbeat is older than HEARTBEAT_STALE_MINUTES."""
    if last_heartbeat is None:
        return True
    # Ensure the datetime is timezone-aware before subtracting.
    lhb = last_heartbeat if last_heartbeat.tzinfo else last_heartbeat.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - lhb) > timedelta(minutes=HEARTBEAT_STALE_MINUTES)


# ---------------------------------------------------------------------------
# Availability logic
# ---------------------------------------------------------------------------


async def is_driver_available_now(
    db: AsyncSession,
    driver_id: int,
) -> bool:
    """Return True if the driver is currently available to receive rides.

    A driver is available when ALL of the following hold:
      1. Their is_online flag is True.
      2. Either they have no schedule slots, OR the current wall-clock time
         falls within an active slot for today's day_of_week.

    day_of_week is resolved via datetime.weekday() so that 0=Monday, 6=Sunday.
    """
    # Check online status first (cheap query).
    result = await db.execute(
        select(DriverOnlineStatus).where(DriverOnlineStatus.driver_id == driver_id)
    )
    status_row = result.scalar_one_or_none()

    if status_row is None or not status_row.is_online:
        return False

    # Fetch active schedule slots for today.
    today_dow = datetime.now(timezone.utc).weekday()
    result = await db.execute(
        select(DriverSchedule).where(
            DriverSchedule.driver_id == driver_id,
            DriverSchedule.day_of_week == today_dow,
            DriverSchedule.is_active.is_(True),
        )
    )
    today_slots = list(result.scalars().all())

    # No schedule set → available whenever online.
    if not today_slots:
        return True

    # Check if current time falls within any active slot.
    now_time: time = datetime.now(timezone.utc).time().replace(tzinfo=None)
    for slot in today_slots:
        if slot.start_time <= now_time <= slot.end_time:
            return True

    return False


async def get_available_drivers_for_matching(db: AsyncSession) -> list[int]:
    """Return driver_ids of all drivers currently available for ride matching.

    Iterates over online drivers and checks is_driver_available_now for each.
    """
    online_ids = await get_online_drivers(db)
    available: list[int] = []
    for driver_id in online_ids:
        if await is_driver_available_now(db, driver_id):
            available.append(driver_id)
    return available
