"""Corporate Ride Policy API endpoints.

Account-admin endpoints (/api/v1/corporate/accounts/me/policy):
  GET    /corporate/accounts/me/policy           — get current policy (any member)
  PUT    /corporate/accounts/me/policy           — create/replace policy (admin only)
  DELETE /corporate/accounts/me/policy           — remove policy (admin only)
  POST   /corporate/accounts/me/policy/check     — validate a proposed ride (any member)

Platform-admin endpoints (/api/v1/admin/corporate/accounts/{id}/policy):
  GET    /admin/corporate/accounts/{id}/policy   — read policy for any account
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_ride_policy import (
    CorporateRidePolicyResponse,
    CorporateRidePolicySet,
    RideCheckRequest,
    RideCheckResponse,
)
from app.services.corporate_ride_policy import (
    check_ride_allowed,
    delete_policy,
    get_policy,
    set_policy,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-ride-policy"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(
    db: AsyncSession,
    user_id: int,
) -> int:
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


# ---------------------------------------------------------------------------
# Account-member routes
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/policy",
    response_model=CorporateRidePolicyResponse,
    summary="Get your company's ride policy",
)
async def get_my_policy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the ride policy for the caller's corporate account.

    Returns 404 if the caller is not a corporate account member, or if no
    policy has been configured.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    policy = await get_policy(db, account_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ride policy has been configured for this account.",
        )
    return policy


@router.put(
    "/corporate/accounts/me/policy",
    response_model=CorporateRidePolicyResponse,
    summary="Create or replace your company's ride policy",
    status_code=status.HTTP_200_OK,
)
async def set_my_policy(
    data: CorporateRidePolicySet,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or replace the ride policy for the caller's corporate account.

    Only account admins may call this endpoint.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await set_policy(db, account_id, data, requesting_user_id=current_user.id)


@router.delete(
    "/corporate/accounts/me/policy",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove your company's ride policy",
)
async def delete_my_policy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove the ride policy for the caller's corporate account.

    Only account admins may call this endpoint.  Returns 404 if no policy
    exists.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    await delete_policy(db, account_id, requesting_user_id=current_user.id)


@router.post(
    "/corporate/accounts/me/policy/check",
    response_model=RideCheckResponse,
    summary="Check whether a ride is permitted by the company policy",
)
async def check_my_policy(
    request: RideCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evaluate a proposed ride against the caller's corporate account policy.

    Any active account member may call this.  When no policy is configured
    ``allowed=true`` is always returned.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await check_ride_allowed(
        db=db,
        account_id=account_id,
        vehicle_category=request.vehicle_category,
        estimated_cost_usd=request.estimated_cost_usd,
        purpose=request.purpose,
        departure_utc_hour=request.departure_utc_hour,
        departure_utc_weekday=request.departure_utc_weekday,
    )


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/policy",
    response_model=CorporateRidePolicyResponse,
    summary="[Admin] Get ride policy for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_get_policy(
    account_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return the ride policy for any corporate account (platform admin only).

    Returns 404 if no policy has been configured.
    """
    policy = await get_policy(db, account_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ride policy has been configured for this account.",
        )
    return policy
