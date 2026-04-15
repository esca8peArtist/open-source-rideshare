"""Service layer for corporate ride policies.

A corporate ride policy is an optional set of rules that governs which rides
employees may charge to a corporate account.  The policy is owned by the
account admin(s) and evaluated at booking time.

Public functions
----------------
get_policy          — fetch the current policy (None if not set)
set_policy          — create-or-replace the policy (account admin only)
delete_policy       — remove the policy (account admin only)
check_ride_allowed  — evaluate a proposed ride against the policy
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import (
    BusinessAccountMember,
    CorporateAccountStatus,
    MemberRole,
)
from app.models.corporate import BusinessAccount
from app.models.corporate_ride_policy import CorporateRidePolicy
from app.schemas.corporate_ride_policy import CorporateRidePolicySet, RideCheckResponse

logger = logging.getLogger(__name__)

# Monday=0 … Friday=4
_BUSINESS_DAYS = frozenset(range(5))
_BUSINESS_HOUR_START = 7   # 07:00 UTC inclusive
_BUSINESS_HOUR_END = 21    # 21:00 UTC exclusive


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
) -> None:
    """Raise HTTP 403 if the user is not an active admin of the account.

    Pass ``requesting_user_id=-1`` from platform-admin endpoints to bypass
    this check.
    """
    if requesting_user_id == -1:
        return

    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == requesting_user_id,
            BusinessAccountMember.is_active.is_(True),
            BusinessAccountMember.role == MemberRole.ADMIN,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only account admins may manage the ride policy.",
        )


async def _get_account_or_404(db: AsyncSession, account_id: int) -> BusinessAccount:
    result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )
    return account


async def _fetch_policy(
    db: AsyncSession, account_id: int
) -> CorporateRidePolicy | None:
    result = await db.execute(
        select(CorporateRidePolicy).where(
            CorporateRidePolicy.account_id == account_id
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


async def get_policy(
    db: AsyncSession,
    account_id: int,
) -> CorporateRidePolicy | None:
    """Return the ride policy for *account_id*, or ``None`` if not configured."""
    return await _fetch_policy(db, account_id)


async def set_policy(
    db: AsyncSession,
    account_id: int,
    data: CorporateRidePolicySet,
    requesting_user_id: int,
) -> CorporateRidePolicy:
    """Create or replace the ride policy for *account_id*.

    Args:
        db: Database session.
        account_id: Target corporate account.
        data: Policy configuration.
        requesting_user_id: Caller's user ID (must be account admin, or -1 for
            platform admins bypassing the check).

    Returns:
        The upserted CorporateRidePolicy.

    Raises:
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: Account not found.
    """
    await _get_account_or_404(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)

    policy = await _fetch_policy(db, account_id)

    if policy is None:
        policy = CorporateRidePolicy(account_id=account_id)
        db.add(policy)

    policy.allowed_vehicle_categories = data.allowed_vehicle_categories
    policy.max_per_ride_usd = data.max_per_ride_usd
    policy.max_per_member_monthly_usd = data.max_per_member_monthly_usd
    policy.require_purpose = data.require_purpose
    policy.approved_purposes = data.approved_purposes
    policy.business_hours_only = data.business_hours_only

    await db.commit()
    await db.refresh(policy)
    logger.info("Corporate ride policy set for account %d", account_id)
    return policy


async def delete_policy(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
) -> None:
    """Remove the ride policy for *account_id*.

    Args:
        db: Database session.
        account_id: Target corporate account.
        requesting_user_id: Caller's user ID (must be account admin, or -1 for
            platform admins bypassing the check).

    Raises:
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: Account or policy not found.
    """
    await _get_account_or_404(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)

    policy = await _fetch_policy(db, account_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ride policy is configured for this account.",
        )

    await db.delete(policy)
    await db.commit()
    logger.info("Corporate ride policy deleted for account %d", account_id)


async def check_ride_allowed(
    db: AsyncSession,
    account_id: int,
    vehicle_category: str,
    estimated_cost_usd: Decimal,
    purpose: str | None,
    departure_utc_hour: int | None,
    departure_utc_weekday: int | None,
) -> RideCheckResponse:
    """Evaluate whether a proposed ride is permitted under the account policy.

    Returns a ``RideCheckResponse`` with ``allowed=True`` when the ride is
    permitted, or ``allowed=False`` with a ``reason`` string describing the
    first violation encountered.

    When no policy is configured for the account every ride is permitted.

    Args:
        db: Database session.
        account_id: Target corporate account.
        vehicle_category: The vehicle category the rider wants to request.
        estimated_cost_usd: Estimated ride fare.
        purpose: Trip purpose supplied by the employee (may be None).
        departure_utc_hour: Hour of departure in UTC (0–23); required when the
            policy has ``business_hours_only=True``.
        departure_utc_weekday: Day of week in UTC (0=Monday … 6=Sunday);
            required when the policy has ``business_hours_only=True``.

    Returns:
        RideCheckResponse
    """
    policy = await _fetch_policy(db, account_id)

    if policy is None:
        return RideCheckResponse(allowed=True)

    # 1. Vehicle category check
    if (
        policy.allowed_vehicle_categories is not None
        and vehicle_category not in policy.allowed_vehicle_categories
    ):
        return RideCheckResponse(
            allowed=False,
            reason=(
                f"Vehicle category '{vehicle_category}' is not permitted by the "
                f"company policy. Allowed: {policy.allowed_vehicle_categories}."
            ),
        )

    # 2. Per-ride cost cap
    if (
        policy.max_per_ride_usd is not None
        and estimated_cost_usd > policy.max_per_ride_usd
    ):
        return RideCheckResponse(
            allowed=False,
            reason=(
                f"Estimated fare ${estimated_cost_usd:.2f} exceeds the company "
                f"per-ride limit of ${policy.max_per_ride_usd:.2f}."
            ),
        )

    # 3. Trip purpose requirement
    if policy.require_purpose:
        if not purpose:
            return RideCheckResponse(
                allowed=False,
                reason="A trip purpose is required by the company policy.",
            )
        if (
            policy.approved_purposes is not None
            and purpose not in policy.approved_purposes
        ):
            return RideCheckResponse(
                allowed=False,
                reason=(
                    f"Purpose '{purpose}' is not on the company's approved list: "
                    f"{policy.approved_purposes}."
                ),
            )

    # 4. Business hours restriction
    if policy.business_hours_only:
        if departure_utc_hour is None or departure_utc_weekday is None:
            return RideCheckResponse(
                allowed=False,
                reason=(
                    "Cannot verify departure time. The company policy restricts "
                    "rides to business hours (Mon–Fri 07:00–21:00 UTC)."
                ),
            )
        if departure_utc_weekday not in _BUSINESS_DAYS:
            return RideCheckResponse(
                allowed=False,
                reason=(
                    "The company policy only permits rides on weekdays "
                    "(Mon–Fri 07:00–21:00 UTC)."
                ),
            )
        if not (_BUSINESS_HOUR_START <= departure_utc_hour < _BUSINESS_HOUR_END):
            return RideCheckResponse(
                allowed=False,
                reason=(
                    "The company policy only permits rides during business hours "
                    f"({_BUSINESS_HOUR_START}:00–{_BUSINESS_HOUR_END}:00 UTC)."
                ),
            )

    return RideCheckResponse(allowed=True)
