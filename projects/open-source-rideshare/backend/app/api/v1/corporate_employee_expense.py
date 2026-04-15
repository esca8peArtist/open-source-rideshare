"""Corporate Employee Spend Limits endpoints.

Employee (self-service) endpoints:
  GET  /corporate/accounts/me/my-spending              — current-month summary + limit
  GET  /corporate/accounts/me/my-spending/history      — monthly trend (last N months)

Admin endpoints (require ADMIN role within the account):
  GET    /corporate/accounts/me/members/spend-limits              — all members overview
  GET    /corporate/accounts/me/members/{user_id}/spend-limit     — single member summary
  PUT    /corporate/accounts/me/members/{user_id}/spend-limit     — set/update limit
  DELETE /corporate/accounts/me/members/{user_id}/spend-limit     — remove limit

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/members/spend-limits — admin mirror of list
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_employee_expense import (
    MemberSpendLimitsResponse,
    MemberSpendSummaryResponse,
    MySpendHistoryResponse,
    MySpendSummaryResponse,
    SetSpendLimitRequest,
    SpendLimitResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_employee_expense import (
    get_member_spend_summary,
    get_my_spend_history,
    get_my_spend_summary,
    list_members_spend_summary,
    remove_member_spend_limit,
    set_member_spend_limit,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-employee-expense"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user or raise HTTP 404."""
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Employee: my spending summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/my-spending",
    response_model=MySpendSummaryResponse,
    summary="My current-month spend and personal limit (employee self-service)",
)
async def my_spend_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated employee's current-month spend, personal monthly
    limit, utilization percentage, and year-to-date totals.

    Any active corporate account member may access this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_my_spend_summary(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Employee: my spending history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/my-spending/history",
    response_model=MySpendHistoryResponse,
    summary="My monthly spend history (employee self-service)",
)
async def my_spend_history(
    months: int = Query(
        6,
        ge=1,
        le=24,
        description="Number of past calendar months to return (1–24).",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated employee's monthly spend trend — ride counts,
    total spend, and average fare per month — ordered newest-first.

    Any active corporate account member may access this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_my_spend_history(db, account_id, user.id, months=months)


# ---------------------------------------------------------------------------
# Admin: list all members with spend limits
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/members/spend-limits",
    response_model=MemberSpendLimitsResponse,
    summary="Admin: overview of all member spend limits and current usage",
)
async def admin_list_member_spend_limits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all account members with their monthly spend limits and
    current-month usage.

    Requires ADMIN role within the corporate account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_members_spend_summary(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Admin: get a single member's spend summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/members/{target_user_id}/spend-limit",
    response_model=MemberSpendSummaryResponse,
    summary="Admin: get spend summary for a specific member",
)
async def admin_get_member_spend(
    target_user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current-month spend summary and limit for a specific member.

    Requires ADMIN role within the corporate account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_member_spend_summary(db, account_id, target_user_id, user.id)


# ---------------------------------------------------------------------------
# Admin: set a member's spend limit
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/members/{target_user_id}/spend-limit",
    response_model=SpendLimitResponse,
    summary="Admin: set or update a member's monthly spend limit",
)
async def admin_set_member_spend_limit(
    target_user_id: int,
    data: SetSpendLimitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or update the monthly spend cap for a specific member.

    Once set, the platform will surface the utilization percentage to the
    employee via the ``/my-spending`` endpoint.  This does not automatically
    block rides over the limit — it is a soft cap for reporting purposes.

    Requires ADMIN role within the corporate account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await set_member_spend_limit(
        db, account_id, target_user_id, user.id, data.monthly_limit_usd
    )
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: remove a member's spend limit
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/members/{target_user_id}/spend-limit",
    response_model=SpendLimitResponse,
    summary="Admin: remove a member's monthly spend limit",
)
async def admin_remove_member_spend_limit(
    target_user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the monthly spend cap for a specific member (set to unlimited).

    Requires ADMIN role within the corporate account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await remove_member_spend_limit(
        db, account_id, target_user_id, user.id
    )
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Platform admin: list all members spend limits for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/members/spend-limits",
    response_model=MemberSpendLimitsResponse,
    summary="Platform admin: member spend limits for any corporate account",
)
async def platform_admin_list_member_spend_limits(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all members with their spend limits and current-month usage for
    any corporate account.

    Requires platform-level admin role.
    """
    # For platform admin, pass account_id as both args — the service's
    # _require_admin check is bypassed by using a dedicated helper below.
    from sqlalchemy import select as sa_select
    from app.models.corporate import BusinessAccountMember, MemberRole
    from app.schemas.corporate_employee_expense import MemberSpendItem
    from decimal import Decimal
    from datetime import date, datetime, timezone
    from sqlalchemy import func

    from app.models.ride import Ride

    now = datetime.now(timezone.utc)
    month_start = date(now.year, now.month, 1)
    month = now.strftime("%Y-%m")

    members_result = await db.execute(
        sa_select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id
        ).order_by(BusinessAccountMember.id)
    )
    members = list(members_result.scalars().all())

    if not members:
        return MemberSpendLimitsResponse(
            account_id=account_id,
            current_month=month,
            members=[],
        )

    user_ids = [m.user_id for m in members]

    spend_result = await db.execute(
        sa_select(
            Ride.rider_id.label("user_id"),
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
        )
        .where(
            Ride.corporate_account_id == account_id,
            Ride.rider_id.in_(user_ids),
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= month_start,
        )
        .group_by(Ride.rider_id)
    )
    spend_map: dict[int, tuple[int, Decimal]] = {}
    for row in spend_result.all():
        spend_map[row.user_id] = (row.rides or 0, Decimal(str(row.spend or 0)))

    from app.services.corporate_employee_expense import _utilization_pct

    items: list[MemberSpendItem] = []
    for m in members:
        cm_rides, cm_spend = spend_map.get(m.user_id, (0, Decimal("0")))
        limit = m.monthly_spend_limit
        items.append(
            MemberSpendItem(
                user_id=m.user_id,
                monthly_spend_limit=limit,
                current_month_rides=cm_rides,
                current_month_spend=cm_spend,
                limit_utilization_pct=_utilization_pct(cm_spend, limit),
                is_active=m.is_active,
            )
        )

    return MemberSpendLimitsResponse(
        account_id=account_id,
        current_month=month,
        members=items,
    )
