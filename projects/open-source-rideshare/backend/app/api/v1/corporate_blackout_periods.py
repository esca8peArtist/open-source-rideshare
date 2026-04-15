"""Corporate Blackout Periods API endpoints.

Admins define named date ranges when corporate bookings are restricted.
Recurrence options: none (one-time), annual, weekly.

The /check endpoint lets callers ask whether a proposed booking datetime
falls within any active blackout window before attempting to book.

Member endpoints (account admin required):
  POST   /corporate/accounts/me/blackout-periods                — create
  GET    /corporate/accounts/me/blackout-periods                — list
  GET    /corporate/accounts/me/blackout-periods/check          — check a datetime
  GET    /corporate/accounts/me/blackout-periods/{period_id}    — get one
  PATCH  /corporate/accounts/me/blackout-periods/{period_id}    — update
  DELETE /corporate/accounts/me/blackout-periods/{period_id}    — delete
  POST   /corporate/accounts/me/blackout-periods/{period_id}/deactivate — soft-disable

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/blackout-periods          — list
  GET    /admin/corporate/accounts/{account_id}/blackout-periods/check    — check
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_blackout_period import (
    BlackoutCheckResponse,
    BlackoutPeriodCreate,
    BlackoutPeriodListResponse,
    BlackoutPeriodResponse,
    BlackoutPeriodUpdate,
)
from app.services.corporate_blackout_period import (
    check_booking_blackout,
    create_blackout_period,
    delete_blackout_period,
    get_blackout_period,
    list_blackout_periods,
    update_blackout_period,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-blackout-periods"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID the user belongs to.

    Raises HTTP 404 if the user is not an active member of any account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return membership.account_id


def _to_response(period) -> BlackoutPeriodResponse:
    return BlackoutPeriodResponse(
        id=period.id,
        corporate_account_id=period.corporate_account_id,
        name=period.name,
        start_datetime=period.start_datetime,
        end_datetime=period.end_datetime,
        recurrence=period.recurrence.value if hasattr(period.recurrence, "value") else period.recurrence,
        affected_days=period.affected_days,
        override_allowed=period.override_allowed,
        override_requires_approval=period.override_requires_approval,
        reason=period.reason,
        is_active=period.is_active,
        created_by_id=period.created_by_id,
        created_at=period.created_at,
        updated_at=period.updated_at,
    )


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/blackout-periods",
    response_model=BlackoutPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a booking blackout period for your corporate account",
)
async def create_my_blackout_period(
    data: BlackoutPeriodCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new date range during which corporate bookings are restricted."""
    account_id = await _get_member_account_id(db, current_user.id)
    period = await create_blackout_period(db, account_id, data, created_by_id=current_user.id)
    return _to_response(period)


@router.get(
    "/corporate/accounts/me/blackout-periods",
    response_model=BlackoutPeriodListResponse,
    summary="List booking blackout periods for your corporate account",
)
async def list_my_blackout_periods(
    active_only: bool = Query(False, description="Only return active periods."),
    from_dt: datetime | None = Query(None, description="Filter: periods ending on or after this datetime."),
    to_dt: datetime | None = Query(None, description="Filter: periods starting on or before this datetime."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all blackout periods for the caller's corporate account."""
    account_id = await _get_member_account_id(db, current_user.id)
    periods, total = await list_blackout_periods(
        db, account_id, active_only=active_only, from_dt=from_dt, to_dt=to_dt,
        skip=skip, limit=limit,
    )
    return BlackoutPeriodListResponse(
        items=[_to_response(p) for p in periods],
        total=total,
    )


@router.get(
    "/corporate/accounts/me/blackout-periods/check",
    response_model=BlackoutCheckResponse,
    summary="Check whether a datetime is covered by a blackout period",
)
async def check_my_blackout(
    dt: datetime = Query(..., description="Proposed booking datetime to check (ISO 8601)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return whether the given datetime falls inside any active blackout window.

    The ``active_periods`` list contains every blackout period that covers
    the requested datetime.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    matching = await check_booking_blackout(db, account_id, dt)
    return BlackoutCheckResponse(
        dt=dt,
        is_blacked_out=len(matching) > 0,
        active_periods=[_to_response(p) for p in matching],
    )


@router.get(
    "/corporate/accounts/me/blackout-periods/{period_id}",
    response_model=BlackoutPeriodResponse,
    summary="Get a specific blackout period",
)
async def get_my_blackout_period(
    period_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single blackout period by ID."""
    account_id = await _get_member_account_id(db, current_user.id)
    period = await get_blackout_period(db, account_id, period_id)
    return _to_response(period)


@router.patch(
    "/corporate/accounts/me/blackout-periods/{period_id}",
    response_model=BlackoutPeriodResponse,
    summary="Update a blackout period",
)
async def update_my_blackout_period(
    period_id: uuid.UUID,
    data: BlackoutPeriodUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update a blackout period."""
    account_id = await _get_member_account_id(db, current_user.id)
    period = await update_blackout_period(db, account_id, period_id, data)
    return _to_response(period)


@router.delete(
    "/corporate/accounts/me/blackout-periods/{period_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a blackout period",
)
async def delete_my_blackout_period(
    period_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a blackout period."""
    account_id = await _get_member_account_id(db, current_user.id)
    await delete_blackout_period(db, account_id, period_id)


@router.post(
    "/corporate/accounts/me/blackout-periods/{period_id}/deactivate",
    response_model=BlackoutPeriodResponse,
    summary="Soft-deactivate a blackout period without deleting it",
)
async def deactivate_my_blackout_period(
    period_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set is_active=False on the blackout period.

    The period remains in the database and can be re-activated with PATCH.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    period = await update_blackout_period(
        db, account_id, period_id, BlackoutPeriodUpdate(is_active=False)
    )
    return _to_response(period)


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/blackout-periods",
    response_model=BlackoutPeriodListResponse,
    summary="[Admin] List blackout periods for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_blackout_periods(
    account_id: int,
    active_only: bool = Query(False),
    from_dt: datetime | None = Query(None),
    to_dt: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List blackout periods for any corporate account (platform admin only)."""
    periods, total = await list_blackout_periods(
        db, account_id, active_only=active_only, from_dt=from_dt, to_dt=to_dt,
        skip=skip, limit=limit,
    )
    return BlackoutPeriodListResponse(
        items=[_to_response(p) for p in periods],
        total=total,
    )


@router.get(
    "/admin/corporate/accounts/{account_id}/blackout-periods/check",
    response_model=BlackoutCheckResponse,
    summary="[Admin] Check whether a datetime is blacked out for any account",
    dependencies=[Depends(require_admin)],
)
async def admin_check_blackout(
    account_id: int,
    dt: datetime = Query(..., description="Datetime to check (ISO 8601)."),
    db: AsyncSession = Depends(get_db),
):
    """Check a proposed booking datetime against any account's blackout periods."""
    matching = await check_booking_blackout(db, account_id, dt)
    return BlackoutCheckResponse(
        dt=dt,
        is_blacked_out=len(matching) > 0,
        active_periods=[_to_response(p) for p in matching],
    )
