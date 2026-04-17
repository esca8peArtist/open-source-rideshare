"""Corporate Member Policy Enforcement endpoints.

Allows the booking engine (and admins) to validate a proposed ride booking
against a member's effective corporate ride policy before submitting the
booking.

Member endpoints (authenticated):
  POST /corporate/accounts/me/check-booking
       — Self-check: validate a booking against own effective policy.

Admin endpoints (require_admin):
  POST /corporate/accounts/{account_id}/members/{member_id}/check-booking
       — Admin: check a booking on behalf of a specific member.
  GET  /corporate/accounts/{account_id}/members/{member_id}/monthly-spend
       — Admin: view a member's current-month spend vs. their policy cap.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_member_policy_enforcement import (
    BookingPolicyCheckRequest,
    BookingPolicyCheckResponse,
    MonthlySpendResponse,
)
from app.services.corporate_member_policy_enforcement import (
    check_booking_against_policy,
    get_member_monthly_spend,
)
from app.services.corporate_member_policy_override import get_effective_policy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-member-policy-enforcement"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_member_for_user(
    db: AsyncSession,
    user_id: int,
) -> tuple[int, int]:
    """Return (account_id, member_id) for the authenticated user.

    Raises HTTP 404 if the user is not an active member of any corporate account.
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
    return membership.account_id, membership.id


# ---------------------------------------------------------------------------
# Member endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/check-booking",
    response_model=BookingPolicyCheckResponse,
    summary="Check a proposed booking against your corporate ride policy",
)
async def member_check_booking(
    payload: BookingPolicyCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate a proposed ride booking against the authenticated member's
    effective corporate ride policy.

    Returns an outcome of ``allowed``, ``requires_approval``, or ``denied``
    along with any policy violations and monthly spend information.

    Any authenticated corporate account member may call this endpoint to
    pre-validate a booking before submission.
    """
    account_id, member_id = await _resolve_member_for_user(db, current_user.id)
    return await check_booking_against_policy(db, account_id, member_id, payload)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/{account_id}/members/{member_id}/check-booking",
    response_model=BookingPolicyCheckResponse,
    summary="[Admin] Check a proposed booking for a specific member",
    dependencies=[Depends(require_admin)],
)
async def admin_check_booking(
    account_id: int,
    member_id: int,
    payload: BookingPolicyCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """Validate a proposed ride booking against a specific member's effective
    corporate ride policy.

    Useful for support tooling and pre-booking validation on behalf of a member.

    Platform admin only.
    """
    return await check_booking_against_policy(db, account_id, member_id, payload)


@router.get(
    "/corporate/accounts/{account_id}/members/{member_id}/monthly-spend",
    response_model=MonthlySpendResponse,
    summary="[Admin] View a member's current-month spend vs. their policy cap",
    dependencies=[Depends(require_admin)],
)
async def admin_get_monthly_spend(
    account_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return a member's total ride spend for the current calendar month and
    compare it against their effective monthly policy cap.

    Platform admin only.
    """
    effective = await get_effective_policy(db, account_id, member_id)
    monthly_spend = await get_member_monthly_spend(db, account_id, member_id)
    monthly_limit = effective.max_per_member_monthly_usd

    if monthly_limit is not None:
        from decimal import Decimal
        monthly_remaining = max(Decimal("0.00"), monthly_limit - monthly_spend)
    else:
        monthly_remaining = None

    now_utc = datetime.now(timezone.utc)
    period = f"{now_utc.year}-{now_utc.month:02d}"

    return MonthlySpendResponse(
        member_id=member_id,
        account_id=account_id,
        monthly_spend_usd=monthly_spend,
        monthly_limit_usd=monthly_limit,
        monthly_remaining_usd=monthly_remaining,
        period=period,
    )
