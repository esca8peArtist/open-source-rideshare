"""Surge waitlist API endpoints.

Rider endpoints (require rider/user auth):
  POST   /surge-waitlist              — join waitlist
  GET    /surge-waitlist/me           — list own entries
  DELETE /surge-waitlist/{entry_id}   — cancel entry

Public endpoint (no auth required):
  GET /surge-waitlist/current-surge   — current surge at a given lat/lon

Admin endpoint (require admin auth):
  POST /admin/surge-waitlist/check    — trigger poll-and-notify cycle
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.surge_waitlist import (
    CurrentSurgeResponse,
    SurgeWaitlistCreate,
    SurgeWaitlistResponse,
    WaitlistCheckResult,
)
from app.services.surge_waitlist import (
    cancel_waitlist_entry,
    check_and_notify_waitlist,
    create_waitlist_entry,
    get_current_surge_for_location,
    get_my_waitlist_entries,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

rider_router = APIRouter(
    prefix="/surge-waitlist",
    tags=["surge-waitlist"],
)

public_router = APIRouter(
    prefix="/surge-waitlist",
    tags=["surge-waitlist"],
)

admin_router = APIRouter(
    prefix="/admin/surge-waitlist",
    tags=["admin", "surge-waitlist"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@rider_router.post(
    "",
    response_model=SurgeWaitlistResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_surge_waitlist(
    body: SurgeWaitlistCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Join the surge waitlist for a given pickup location.

    The rider will be notified when the surge multiplier at ``origin_lat``/
    ``origin_lon`` drops to or below ``max_multiplier``. The entry expires
    automatically after 2 hours if not already notified.
    """
    entry = await create_waitlist_entry(
        db=db,
        rider_id=current_user.id,
        origin_lat=body.origin_lat,
        origin_lon=body.origin_lon,
        dest_lat=body.destination_lat,
        dest_lon=body.destination_lon,
        max_multiplier=body.max_multiplier,
        vehicle_pref=body.vehicle_preference,
        notify_push=body.notify_via_push,
        notify_sms=body.notify_via_sms,
    )
    return SurgeWaitlistResponse.from_entry(entry)


@rider_router.get(
    "/me",
    response_model=list[SurgeWaitlistResponse],
)
async def list_my_waitlist_entries(
    include_expired: bool = Query(False, description="Include expired/cancelled entries"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current rider's surge waitlist entries.

    By default only active and notified entries are returned. Pass
    ``include_expired=true`` to also include expired and cancelled entries.
    """
    entries = await get_my_waitlist_entries(
        db=db,
        rider_id=current_user.id,
        include_expired=include_expired,
    )
    return [SurgeWaitlistResponse.from_entry(e) for e in entries]


@rider_router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_my_waitlist_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an active waitlist entry.

    The caller must own the entry. Attempting to cancel an entry that belongs
    to another rider returns 403. Cancelling a non-active entry returns 400.
    """
    await cancel_waitlist_entry(db=db, entry_id=entry_id, rider_id=current_user.id)


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------


@public_router.get(
    "/current-surge",
    response_model=CurrentSurgeResponse,
)
async def get_current_surge(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitude"),
    db: AsyncSession = Depends(get_db),
):
    """Return the current surge multiplier and zone name for a location.

    No authentication required. Intended for pre-ride fare estimation and
    waitlist decision-making.
    """
    surge_info = await get_current_surge_for_location(db=db, lat=lat, lon=lon)
    return CurrentSurgeResponse(**surge_info)


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------


@admin_router.post(
    "/check",
    response_model=WaitlistCheckResult,
)
async def trigger_waitlist_check(
    db: AsyncSession = Depends(get_db),
):
    """Trigger a full poll-and-notify pass over all active waitlist entries.

    This endpoint is normally called by a background scheduler. Admins can
    invoke it manually to trigger an immediate check. Returns counts of
    notified, expired, and still-active entries.
    """
    result = await check_and_notify_waitlist(db=db)
    return WaitlistCheckResult(**result)
