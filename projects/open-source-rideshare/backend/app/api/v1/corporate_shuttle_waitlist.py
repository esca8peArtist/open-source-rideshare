"""Corporate Shuttle Waitlist endpoints.

When a shuttle schedule run is at full capacity employees can join a waitlist
for a specific date. The first waiting member is automatically promoted to a
confirmed seat when an existing booking is cancelled.

Member endpoints (any authenticated account member):
  POST /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist
                                                          — join waitlist → 201
  GET  /api/v1/corporate/{account_id}/shuttle/my-waitlists
                                                          — member's own entries
  GET  /api/v1/corporate/{account_id}/shuttle/waitlist/{entry_id}
                                                          — get one entry
  POST /api/v1/corporate/{account_id}/shuttle/waitlist/{entry_id}/leave
                                                          — leave (cancel) entry

Admin endpoints (account admins only):
  GET  /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist
                                                          — schedule waitlist
  GET  /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist/summary
                                                          — waitlist summary

Platform-admin endpoints:
  GET /api/v1/platform/corporate/shuttle/waitlist/all    — all entries
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_shuttle_waitlist import WaitlistStatus
from app.models.user import User
from app.schemas.corporate_shuttle_waitlist import (
    WaitlistJoinRequest,
    WaitlistLeaveRequest,
    WaitlistResponse,
    WaitlistSummaryResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_shuttle_waitlist_service import (
    get_member_waitlists,
    get_schedule_waitlist,
    get_waitlist_entry,
    get_waitlist_summary,
    join_waitlist,
    leave_waitlist,
    list_all_platform,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Shuttle Waitlist"])


# ---------------------------------------------------------------------------
# Member: join waitlist
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist",
    response_model=WaitlistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Join the waitlist for a shuttle schedule",
)
async def join_waitlist_endpoint(
    account_id: int,
    schedule_id: uuid.UUID,
    data: WaitlistJoinRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add the calling user to the waitlist for the given schedule and date.

    Returns 404 if the schedule is not found.
    Returns 409 if the schedule is inactive, the member already has an active
    booking, or the member is already on the waitlist for this date.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await join_waitlist(
        db,
        schedule_id=schedule_id,
        account_id=account_id,
        member_id=user.id,
        booking_date=data.booking_date,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Member: list own waitlist entries  ← MUST be before /waitlist/{entry_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/my-waitlists",
    response_model=List[WaitlistResponse],
    summary="List the current user's shuttle waitlist entries",
)
async def list_my_waitlists_endpoint(
    account_id: int,
    waitlist_status: Optional[WaitlistStatus] = Query(
        None, alias="status", description="Filter by waitlist status"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all waitlist entries for the calling user within the account.

    Optionally filter by status (waiting/promoted/expired/cancelled).
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_member_waitlists(db, account_id, user.id, status_filter=waitlist_status)


# ---------------------------------------------------------------------------
# Member: get a single entry
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/waitlist/{entry_id}",
    response_model=WaitlistResponse,
    summary="Get a shuttle waitlist entry",
)
async def get_waitlist_entry_endpoint(
    account_id: int,
    entry_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single waitlist entry by ID.

    Returns 404 if not found or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_waitlist_entry(db, entry_id, account_id)


# ---------------------------------------------------------------------------
# Member: leave (cancel) waitlist entry
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/waitlist/{entry_id}/leave",
    response_model=WaitlistResponse,
    summary="Leave a shuttle waitlist",
)
async def leave_waitlist_endpoint(
    account_id: int,
    entry_id: uuid.UUID,
    data: WaitlistLeaveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a waitlist entry for the calling user.

    Returns 404 if not found. Returns 409 if the entry is not in 'waiting'
    status (already promoted, expired, or cancelled).
    Any authenticated account member may leave their own waitlist entry.
    """
    await get_account(db, account_id)
    return await leave_waitlist(db, entry_id, account_id, reason=data.reason)


# ---------------------------------------------------------------------------
# Admin: list waitlist for a schedule+date
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist",
    response_model=List[WaitlistResponse],
    summary="List the waitlist for a shuttle schedule on a specific date (admin only)",
)
async def get_schedule_waitlist_endpoint(
    account_id: int,
    schedule_id: uuid.UUID,
    booking_date: date = Query(..., description="Run date (YYYY-MM-DD)"),
    waitlist_status: Optional[WaitlistStatus] = Query(
        None, alias="status", description="Filter by waitlist status"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return waitlist entries for the given schedule and date.

    Ordered by queue_position ascending. Optionally filter by status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_schedule_waitlist(
        db, schedule_id, account_id, booking_date, status_filter=waitlist_status
    )


# ---------------------------------------------------------------------------
# Admin: waitlist summary for a schedule+date
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist/summary",
    response_model=WaitlistSummaryResponse,
    summary="Get aggregate waitlist statistics for a schedule date (admin only)",
)
async def get_waitlist_summary_endpoint(
    account_id: int,
    schedule_id: uuid.UUID,
    booking_date: date = Query(..., description="Run date (YYYY-MM-DD)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate waitlist stats: waiting_count, promoted_count, total.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_waitlist_summary(db, schedule_id, account_id, booking_date)


# ---------------------------------------------------------------------------
# Platform-admin: cross-account listing
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/shuttle/waitlist/all",
    response_model=List[WaitlistResponse],
    summary="Admin: list all shuttle waitlist entries across all accounts",
)
async def platform_list_all_endpoint(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    waitlist_status: Optional[WaitlistStatus] = Query(
        None, alias="status", description="Filter by waitlist status"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return shuttle waitlist entries across all corporate accounts.

    Platform admin only. Optionally filter by account_id or status.
    """
    return await list_all_platform(db, account_id=account_id, status_filter=waitlist_status)
