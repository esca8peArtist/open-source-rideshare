"""Driver availability and scheduling API endpoints.

Driver-facing:
  GET  /drivers/me/availability                     — get own schedule + online status
  POST /drivers/me/availability/schedule            — add/update a weekly slot
  DELETE /drivers/me/availability/schedule/{slot_id} — remove a slot
  PUT  /drivers/me/availability/online              — go online or offline
  POST /drivers/me/availability/heartbeat           — keep-alive ping
  POST /drivers/me/availability/break/start         — start a break (pause dispatch)
  POST /drivers/me/availability/break/end           — end break (resume dispatch)

Admin-facing:
  GET /admin/drivers/availability                   — all drivers + online state
  GET /admin/drivers/{driver_id}/availability       — single driver detail
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_driver
from app.models.driver import DriverProfile
from app.models.driver_availability import DriverOnlineStatus
from app.models.user import User
from app.schemas.driver_availability import (
    AdminDriverAvailabilityDetail,
    AdminDriverAvailabilityItem,
    BreakResponse,
    DriverAvailabilityResponse,
    OnlineStatusResponse,
    ScheduleSlotCreate,
    ScheduleSlotResponse,
    SetOnlineRequest,
    WeeklyScheduleResponse,
)
from app.services.driver_availability import (
    delete_schedule_slot,
    end_break,
    get_driver_schedule,
    get_online_drivers,
    is_driver_available_now,
    set_driver_online,
    set_schedule_slot,
    start_break,
    update_heartbeat,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-availability"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_driver_profile(db: AsyncSession, user: User) -> DriverProfile:
    """Fetch the DriverProfile for the authenticated user or raise 404."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )
    return profile


# ---------------------------------------------------------------------------
# Driver self-service endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/availability",
    response_model=DriverAvailabilityResponse,
    summary="Get own schedule and online status",
)
async def get_my_availability(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's full weekly schedule and current online status."""
    profile = await _get_driver_profile(db, user)

    slots = await get_driver_schedule(db, profile.id)
    weekly = WeeklyScheduleResponse.from_slots(slots)

    result = await db.execute(
        select(DriverOnlineStatus).where(DriverOnlineStatus.driver_id == profile.id)
    )
    status_row = result.scalar_one_or_none()
    online_resp = OnlineStatusResponse.model_validate(status_row) if status_row else None

    return DriverAvailabilityResponse(online_status=online_resp, schedule=weekly)


@router.post(
    "/drivers/me/availability/schedule",
    response_model=ScheduleSlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add or update a weekly availability slot",
)
async def upsert_schedule_slot(
    slot: ScheduleSlotCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a recurring weekly availability slot.

    If a slot already exists for the same day and start_time it is updated
    in-place (upsert semantics).
    """
    profile = await _get_driver_profile(db, user)
    db_slot = await set_schedule_slot(db, profile.id, slot)
    return ScheduleSlotResponse.model_validate(db_slot)


@router.delete(
    "/drivers/me/availability/schedule/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a weekly availability slot",
)
async def remove_schedule_slot(
    slot_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific schedule slot owned by the authenticated driver."""
    profile = await _get_driver_profile(db, user)
    deleted = await delete_schedule_slot(db, profile.id, slot_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule slot not found.",
        )


@router.put(
    "/drivers/me/availability/online",
    response_model=OnlineStatusResponse,
    summary="Set online or offline",
)
async def set_online_status(
    req: SetOnlineRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the driver's online/offline state.

    Setting ``is_online=true`` stamps ``went_online_at`` with the current
    timestamp if the driver was previously offline.
    """
    profile = await _get_driver_profile(db, user)
    status_row = await set_driver_online(db, profile.id, req.is_online)
    return OnlineStatusResponse.model_validate(status_row)


@router.post(
    "/drivers/me/availability/heartbeat",
    response_model=OnlineStatusResponse,
    summary="Send a keep-alive heartbeat",
)
async def send_heartbeat(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Update the driver's last_heartbeat timestamp.

    Clients should call this endpoint every 1–2 minutes while the driver app
    is active.  If the heartbeat becomes stale (>5 min), the driver will be
    auto-offlined by the background sweep task.
    """
    profile = await _get_driver_profile(db, user)
    status_row = await update_heartbeat(db, profile.id)
    return OnlineStatusResponse.model_validate(status_row)


# ---------------------------------------------------------------------------
# Break management endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/availability/break/start",
    response_model=BreakResponse,
    summary="Start a break — pauses dispatch without going offline",
)
async def start_driver_break(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Put the driver on break.

    The driver must be online.  While on break the driver is excluded from
    ride dispatch but remains in the "online" pool and can end their break
    at any time.  Idempotent: calling while already on break is safe.
    """
    profile = await _get_driver_profile(db, user)
    try:
        status_row = await start_break(db, profile.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return BreakResponse.model_validate(status_row)


@router.post(
    "/drivers/me/availability/break/end",
    response_model=BreakResponse,
    summary="End a break — resumes dispatch eligibility",
)
async def end_driver_break(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """End the driver's current break and return to active availability.

    The driver must be online.  Idempotent: calling when not on break is safe.
    The heartbeat timestamp is refreshed so the driver isn't immediately
    considered stale by the background sweep.
    """
    profile = await _get_driver_profile(db, user)
    try:
        status_row = await end_break(db, profile.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return BreakResponse.model_validate(status_row)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/availability",
    response_model=list[AdminDriverAvailabilityItem],
    summary="List all drivers with online state (admin only)",
)
async def admin_list_driver_availability(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all drivers that have an online-status row, with availability flag."""
    result = await db.execute(select(DriverOnlineStatus))
    all_statuses = list(result.scalars().all())

    items: list[AdminDriverAvailabilityItem] = []
    for s in all_statuses:
        available = await is_driver_available_now(db, s.driver_id)
        items.append(
            AdminDriverAvailabilityItem(
                driver_id=s.driver_id,
                is_online=s.is_online,
                is_on_break=s.is_on_break,
                went_online_at=s.went_online_at,
                last_heartbeat=s.last_heartbeat,
                is_available_now=available,
            )
        )
    return items


@router.get(
    "/admin/drivers/{driver_id}/availability",
    response_model=AdminDriverAvailabilityDetail,
    summary="Get a single driver's full availability (admin only)",
)
async def admin_get_driver_availability(
    driver_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return schedule + online status + availability flag for one driver."""
    # Verify the driver profile exists.
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Driver profile {driver_id} not found.",
        )

    slots = await get_driver_schedule(db, driver_id)
    weekly = WeeklyScheduleResponse.from_slots(slots)

    result = await db.execute(
        select(DriverOnlineStatus).where(DriverOnlineStatus.driver_id == driver_id)
    )
    status_row = result.scalar_one_or_none()
    online_resp = OnlineStatusResponse.model_validate(status_row) if status_row else None

    available = await is_driver_available_now(db, driver_id)

    return AdminDriverAvailabilityDetail(
        driver_id=driver_id,
        is_available_now=available,
        online_status=online_resp,
        schedule=weekly,
    )
