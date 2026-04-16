"""Corporate Booking Eligibility Check API endpoints.

Provides pre-booking eligibility checks that orchestrate all existing
corporate policy infrastructure into a single consolidated verdict.

Member / admin routes (prefix /api/v1/corporate/accounts/me):
  POST /rides/check-eligibility
      Self-check: an authenticated corporate member checks their own eligibility.
  POST /members/{member_id}/rides/check-eligibility
      Admin check: account admin checks eligibility for any member.

Platform-admin routes (prefix /api/v1/platform/corporate):
  POST /accounts/{account_id}/members/{member_id}/rides/check-eligibility
      Platform admin performs an eligibility check for any account/member pair.

All endpoints return ``BookingEligibilityResponse``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.user import User
from app.schemas.corporate_booking_eligibility import (
    BookingEligibilityResponse,
    BookingRideParams,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_booking_eligibility import check_booking_eligibility
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-booking-eligibility"])

_SELF_CHECK_URL = "/corporate/accounts/me/rides/check-eligibility"
_ADMIN_CHECK_URL = "/corporate/accounts/me/members/{member_id}/rides/check-eligibility"
_PLATFORM_CHECK_URL = (
    "/platform/corporate/accounts/{account_id}/members/{member_id}/rides/check-eligibility"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account(db: AsyncSession, user_id: int):
    """Return the BusinessAccount for an authenticated member.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account


async def _resolve_member_id(
    db: AsyncSession, account_id: int, user_id: int
) -> int:
    """Return BusinessAccountMember.id for a user+account pair.

    Raises HTTP 404 if no active membership exists.
    """
    result = await db.execute(
        sa_select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active corporate membership not found.",
        )
    return membership.id


async def _verify_member_in_account(
    db: AsyncSession, account_id: int, member_id: int
) -> None:
    """Raise HTTP 404 if member_id does not belong to account_id."""
    result = await db.execute(
        sa_select(BusinessAccountMember).where(
            BusinessAccountMember.id == member_id,
            BusinessAccountMember.account_id == account_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this corporate account.",
        )


# ---------------------------------------------------------------------------
# Member self-check endpoint
# ---------------------------------------------------------------------------


@router.post(
    _SELF_CHECK_URL,
    response_model=BookingEligibilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Check your own corporate ride eligibility",
)
async def self_check_eligibility(
    params: BookingRideParams,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingEligibilityResponse:
    """Evaluate whether the current member is eligible to book a corporate ride.

    Resolves the caller's corporate account and member record automatically.
    Returns a full eligibility verdict including policy, blackout, quota,
    spend limit, auto-approval, and approval chain checks.

    Returns 404 if the caller is not a member of any corporate account.
    Returns 200 (not 4xx) even when eligible=False — the HTTP status code
    reflects the success of the check operation, not the eligibility verdict.
    """
    account = await _resolve_account(db, current_user.id)
    member_id = await _resolve_member_id(db, account.id, current_user.id)
    return await check_booking_eligibility(db, account.id, member_id, params)


# ---------------------------------------------------------------------------
# Admin check endpoint (for any member in the account)
# ---------------------------------------------------------------------------


@router.post(
    _ADMIN_CHECK_URL,
    response_model=BookingEligibilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin: check eligibility for any member in the account",
)
async def admin_check_eligibility(
    member_id: int,
    params: BookingRideParams,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingEligibilityResponse:
    """Check corporate ride eligibility for any member in the admin's account.

    Requires the caller to have the ADMIN role in their corporate account.
    Returns 403 when the caller is not an admin.
    Returns 404 when the specified member does not belong to the account.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, account.id, current_user.id)
    await _verify_member_in_account(db, account.id, member_id)
    return await check_booking_eligibility(db, account.id, member_id, params)


# ---------------------------------------------------------------------------
# Platform-admin endpoint
# ---------------------------------------------------------------------------


@router.post(
    _PLATFORM_CHECK_URL,
    response_model=BookingEligibilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Platform admin: check eligibility for any account/member pair",
)
async def platform_check_eligibility(
    account_id: int,
    member_id: int,
    params: BookingRideParams,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> BookingEligibilityResponse:
    """Platform-admin eligibility check for any corporate account and member.

    Requires platform-admin role (``require_admin`` dependency).
    Returns 404 when the member does not belong to the specified account.
    """
    await _verify_member_in_account(db, account_id, member_id)
    return await check_booking_eligibility(db, account_id, member_id, params)
