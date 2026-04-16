"""Corporate Recurring Ride Schedule endpoints.

Employees configure personal recurring ride schedules — daily commutes,
weekly airport runs, monthly off-site meetings — that track their standing
transportation needs and can generate booking records.

Member endpoints (any active account member — own schedules only):
  POST   /corporate/recurring-rides                         — create (201)
  GET    /corporate/recurring-rides                         — list mine
  GET    /corporate/recurring-rides/{ride_id}               — get
  PUT    /corporate/recurring-rides/{ride_id}               — update
  POST   /corporate/recurring-rides/{ride_id}/activate      — activate
  POST   /corporate/recurring-rides/{ride_id}/deactivate    — deactivate
  DELETE /corporate/recurring-rides/{ride_id}               — delete (204)
  GET    /corporate/recurring-rides/{ride_id}/bookings      — booking history

Admin endpoints (account admins only):
  GET  /corporate/admin/recurring-rides         — list all for account
  GET  /corporate/admin/recurring-rides/active  — list active for account

Platform-admin endpoints:
  GET  /platform-admin/corporate/recurring-rides/all                — all schedules
  GET  /platform-admin/corporate/recurring-rides/account/{account_id} — for account
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_recurring_ride import RecurringRideBookingStatus
from app.models.user import User
from app.schemas.corporate_recurring_ride import (
    RecurringRideBookingListResponse,
    RecurringRideCreate,
    RecurringRideListResponse,
    RecurringRideResponse,
    RecurringRideUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_recurring_ride import (
    activate_recurring_ride,
    create_recurring_ride,
    deactivate_recurring_ride,
    delete_recurring_ride,
    get_recurring_ride,
    list_account_recurring_rides,
    list_all_platform,
    list_booking_history,
    list_recurring_rides,
    update_recurring_ride,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-recurring-rides"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_and_member(
    db: AsyncSession,
    user_id: int,
) -> tuple[int, int]:
    """Return (account_id, user_id) for the authenticated user.

    The ``member_id`` stored in recurring-ride tables is the user's own ``id``
    (FK to ``users.id``), matching the transport-preferences pattern.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id, user_id


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
# Member: create
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/recurring-rides",
    response_model=RecurringRideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring ride schedule",
)
async def create_ride_endpoint(
    data: RecurringRideCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new recurring-ride schedule for the authenticated employee.

    Returns 409 if you already have a schedule with this name.
    Returns 404 if you are not a corporate account member.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await create_recurring_ride(db, account_id, member_id, data)


# ---------------------------------------------------------------------------
# Member: list own
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/recurring-rides",
    response_model=RecurringRideListResponse,
    summary="List my recurring ride schedules",
)
async def list_rides_endpoint(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all recurring-ride schedules for the authenticated employee.

    Optionally filter by ``is_active``.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await list_recurring_rides(
        db, account_id, member_id, is_active=is_active
    )


# ---------------------------------------------------------------------------
# Member: get specific
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/recurring-rides/{ride_id}",
    response_model=RecurringRideResponse,
    summary="Get a specific recurring ride schedule",
)
async def get_ride_endpoint(
    ride_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific recurring-ride schedule owned by the authenticated employee.

    Returns 404 if not found or owned by a different member.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await get_recurring_ride(db, ride_id, account_id, member_id)


# ---------------------------------------------------------------------------
# Member: update
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/recurring-rides/{ride_id}",
    response_model=RecurringRideResponse,
    summary="Update a recurring ride schedule",
)
async def update_ride_endpoint(
    ride_id: uuid.UUID,
    data: RecurringRideUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a recurring-ride schedule.

    Returns 404 if not found.  Returns 409 on duplicate name.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await update_recurring_ride(db, ride_id, account_id, member_id, data)


# ---------------------------------------------------------------------------
# Member: activate
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/recurring-rides/{ride_id}/activate",
    response_model=RecurringRideResponse,
    summary="Activate a recurring ride schedule",
)
async def activate_ride_endpoint(
    ride_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate a paused recurring-ride schedule.

    Returns 409 if already active.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await activate_recurring_ride(db, ride_id, account_id, member_id)


# ---------------------------------------------------------------------------
# Member: deactivate
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/recurring-rides/{ride_id}/deactivate",
    response_model=RecurringRideResponse,
    summary="Deactivate a recurring ride schedule",
)
async def deactivate_ride_endpoint(
    ride_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause a recurring-ride schedule without deleting it.

    Returns 409 if already inactive.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await deactivate_recurring_ride(db, ride_id, account_id, member_id)


# ---------------------------------------------------------------------------
# Member: delete
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/recurring-rides/{ride_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recurring ride schedule",
)
async def delete_ride_endpoint(
    ride_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a recurring-ride schedule and all its booking history.

    Returns 409 if active — deactivate first.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    await delete_recurring_ride(db, ride_id, account_id, member_id)


# ---------------------------------------------------------------------------
# Member: booking history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/recurring-rides/{ride_id}/bookings",
    response_model=RecurringRideBookingListResponse,
    summary="Get booking history for a recurring ride schedule",
)
async def booking_history_endpoint(
    ride_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated booking history for a recurring-ride schedule.

    Records are returned newest-first.  Returns 404 if the schedule is
    not found or belongs to a different member.
    """
    account_id, member_id = await _resolve_account_and_member(db, user.id)
    return await list_booking_history(
        db, ride_id, account_id, member_id, limit=limit, offset=offset
    )


# ---------------------------------------------------------------------------
# Admin: list all for account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/admin/recurring-rides",
    response_model=RecurringRideListResponse,
    summary="List all recurring ride schedules for the account (admin only)",
)
async def admin_list_rides_endpoint(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all recurring-ride schedules for the account.

    Includes schedules from all employees.  Only account admins may call
    this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_recurring_rides(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Admin: list active for account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/admin/recurring-rides/active",
    response_model=RecurringRideListResponse,
    summary="List active recurring ride schedules for the account (admin only)",
)
async def admin_list_active_rides_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return only active recurring-ride schedules for the account.

    Convenience shorthand for ``GET /corporate/admin/recurring-rides?is_active=true``.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_recurring_rides(db, account_id, is_active=True)


# ---------------------------------------------------------------------------
# Platform-admin: list all
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/recurring-rides/all",
    response_model=RecurringRideListResponse,
    summary="Platform admin: list all recurring ride schedules",
)
async def platform_list_all_endpoint(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all recurring-ride schedules across all corporate accounts.

    Optionally filter by ``account_id``.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list for specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/recurring-rides/account/{account_id}",
    response_model=RecurringRideListResponse,
    summary="Platform admin: list recurring ride schedules for a specific account",
)
async def platform_list_account_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all recurring-ride schedules for a specific corporate account.

    Optionally filter by ``is_active``.  Platform admin only.
    """
    return await list_account_recurring_rides(db, account_id, is_active=is_active)
