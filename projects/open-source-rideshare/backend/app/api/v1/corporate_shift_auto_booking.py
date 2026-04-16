"""Corporate Shift Auto-Booking endpoints.

When a shift assignment has ``auto_request_rides = True``, admins can
generate pending auto-booking records for upcoming shift dates.  Each
record can then be processed (a Ride is created) or cancelled.

Member endpoints (any active member):
  GET  /corporate/accounts/me/shift-auto-bookings/my              — my bookings
  GET  /corporate/accounts/me/shift-auto-bookings/{booking_id}    — get one
  POST /corporate/accounts/me/shift-auto-bookings/{booking_id}/cancel — cancel

Admin endpoints (account admins only):
  POST /corporate/accounts/me/shift-auto-bookings/generate                  — generate
  GET  /corporate/accounts/me/shift-auto-bookings                           — list all
  GET  /corporate/accounts/me/shifts/{shift_id}/auto-bookings               — shift-scoped
  GET  /corporate/accounts/me/shifts/{shift_id}/auto-bookings/summary       — summary
  POST /corporate/accounts/me/shift-auto-bookings/{booking_id}/process      — process

Platform-admin endpoints:
  GET  /platform/corporate/shift-auto-bookings                    — all accounts
  GET  /platform/corporate/accounts/{account_id}/shift-auto-bookings — one account
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_shift_auto_booking import (
    ShiftAutoBookingDirection,
    ShiftAutoBookingStatus,
)
from app.models.user import User
from app.schemas.corporate_shift_auto_booking import (
    AutoBookingListResponse,
    AutoBookingResponse,
    GenerateAutoBookingsRequest,
    GenerateAutoBookingsResponse,
    ShiftAutoBookingSummaryResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_shift_auto_booking import (
    cancel_shift_auto_booking,
    generate_shift_auto_bookings,
    get_shift_auto_booking,
    get_shift_auto_booking_summary,
    list_all_platform,
    list_member_auto_bookings,
    list_shift_auto_bookings,
    process_shift_auto_booking,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Shift Auto-Booking"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list my auto-bookings  (MUST precede /{booking_id})
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shift-auto-bookings/my",
    response_model=AutoBookingListResponse,
    summary="List my shift auto-bookings",
)
async def list_my_auto_bookings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all shift auto-booking records for the authenticated member.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    # member_id in shift assignments maps to corporate_account_members.id;
    # we use the user.id as proxy here — service filters by that column.
    return await list_member_auto_bookings(db, account_id, member_id=user.id)


# ---------------------------------------------------------------------------
# Admin: generate auto-bookings  (MUST precede /{booking_id})
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shift-auto-bookings/generate",
    response_model=GenerateAutoBookingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate pending shift auto-bookings (admin only)",
)
async def generate_auto_bookings(
    data: GenerateAutoBookingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scan active shift assignments and create pending auto-booking records.

    For every active assignment with ``auto_request_rides = True``, creates
    one ``to_work`` booking per upcoming shift date (and optionally one
    ``from_work`` booking).  Existing records are silently skipped.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await generate_shift_auto_bookings(db, account_id, data)


# ---------------------------------------------------------------------------
# Member: get single auto-booking
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shift-auto-bookings/{booking_id}",
    response_model=AutoBookingResponse,
    summary="Get a shift auto-booking record",
)
async def get_auto_booking(
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single shift auto-booking record.

    Any active member may call this endpoint.  Returns 404 if the record
    does not exist or belongs to a different account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_shift_auto_booking(db, booking_id, account_id)


# ---------------------------------------------------------------------------
# Member / Admin: cancel auto-booking
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shift-auto-bookings/{booking_id}/cancel",
    response_model=AutoBookingResponse,
    summary="Cancel a pending shift auto-booking",
)
async def cancel_auto_booking(
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending auto-booking record.

    Returns 409 if the booking is not in ``pending`` status.
    Any active member may cancel their own bookings; admins can cancel any.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await cancel_shift_auto_booking(db, booking_id, account_id)


# ---------------------------------------------------------------------------
# Admin: process auto-booking
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shift-auto-bookings/{booking_id}/process",
    response_model=AutoBookingResponse,
    summary="Process a pending shift auto-booking — creates the Ride (admin only)",
)
async def process_auto_booking(
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a scheduled Ride for a pending auto-booking record.

    Derives pickup/dropoff from the shift assignment and shift addresses.
    Returns 409 if the booking is not in ``pending`` status.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await process_shift_auto_booking(db, booking_id, account_id)


# ---------------------------------------------------------------------------
# Admin: list all auto-bookings for account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shift-auto-bookings",
    response_model=AutoBookingListResponse,
    summary="List all shift auto-bookings for own account (admin only)",
)
async def list_account_auto_bookings(
    shift_id: Optional[int] = Query(None, description="Filter by shift ID"),
    member_id: Optional[int] = Query(None, description="Filter by member ID"),
    booking_status: Optional[ShiftAutoBookingStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    direction: Optional[ShiftAutoBookingDirection] = Query(
        None, description="Filter by ride direction"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all auto-booking records for the authenticated admin's account.

    Supports filtering by shift, member, status, and direction.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_shift_auto_bookings(
        db,
        account_id,
        shift_id=shift_id,
        member_id=member_id,
        booking_status=booking_status,
        direction=direction,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Admin: list auto-bookings for a specific shift
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts/{shift_id}/auto-bookings",
    response_model=AutoBookingListResponse,
    summary="List auto-bookings for a specific shift (admin only)",
)
async def list_shift_auto_bookings_endpoint(
    shift_id: int,
    booking_status: Optional[ShiftAutoBookingStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    direction: Optional[ShiftAutoBookingDirection] = Query(
        None, description="Filter by ride direction"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all auto-booking records for one shift.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_shift_auto_bookings(
        db,
        account_id,
        shift_id=shift_id,
        booking_status=booking_status,
        direction=direction,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Admin: shift auto-booking summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts/{shift_id}/auto-bookings/summary",
    response_model=ShiftAutoBookingSummaryResponse,
    summary="Get auto-booking summary stats for a shift (admin only)",
)
async def get_auto_booking_summary(
    shift_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate statistics (pending / booked / failed / etc.) for
    all auto-bookings linked to one shift.

    Returns 404 if the shift does not exist in this account.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_shift_auto_booking_summary(db, shift_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all auto-bookings
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/shift-auto-bookings",
    response_model=AutoBookingListResponse,
    summary="Admin: list shift auto-bookings across all accounts",
)
async def admin_list_all_auto_bookings(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    booking_status: Optional[ShiftAutoBookingStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return shift auto-booking records across all accounts.

    Platform admin only.
    """
    return await list_all_platform(
        db,
        account_id=account_id,
        booking_status=booking_status,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Platform-admin: list auto-bookings for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/shift-auto-bookings",
    response_model=AutoBookingListResponse,
    summary="Admin: list shift auto-bookings for a specific account",
)
async def admin_list_account_auto_bookings(
    account_id: int,
    booking_status: Optional[ShiftAutoBookingStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return shift auto-booking records for any account.

    Platform admin only.
    """
    return await list_all_platform(
        db,
        account_id=account_id,
        booking_status=booking_status,
        limit=limit,
        offset=offset,
    )
