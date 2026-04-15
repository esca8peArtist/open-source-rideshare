"""Service layer for Corporate Employee Spend Limits.

Corporate admins can set per-employee monthly spend caps.  Employees can
view their own current-month usage against that cap.  Admins see an overview
of all members' limits and live usage.

All queries operate against the ``corporate_account_members`` table
(BusinessAccountMember) and the ``rides`` table.

Public surface
--------------
get_my_spend_summary(db, account_id, user_id)
get_my_spend_history(db, account_id, user_id, months=6)
get_member_spend_summary(db, account_id, target_user_id, requesting_user_id)
list_members_spend_summary(db, account_id, requesting_user_id)
set_member_spend_limit(db, account_id, target_user_id, requesting_user_id, monthly_limit_usd)
remove_member_spend_limit(db, account_id, target_user_id, requesting_user_id)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_employee_expense import (
    MemberSpendItem,
    MemberSpendLimitsResponse,
    MemberSpendSummaryResponse,
    MySpendHistoryPoint,
    MySpendHistoryResponse,
    MySpendSummaryResponse,
    SpendLimitResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _month_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _utilization_pct(spend: Decimal, limit: Decimal | None) -> float | None:
    """Return utilization as a rounded percentage, or None if no limit."""
    if limit is None or limit == 0:
        return None
    return float(
        (spend / limit * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def _safe_avg(total: Decimal, count: int) -> Decimal | None:
    if count == 0:
        return None
    return (total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _require_active_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return member row or raise HTTP 403."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return member row or raise HTTP 403 if not admin."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _fetch_target_member(
    db: AsyncSession,
    account_id: int,
    target_user_id: int,
) -> BusinessAccountMember:
    """Return target member or raise HTTP 404."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == target_user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this corporate account.",
        )
    return member


async def _current_month_spend_for_user(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    month_start: date,
) -> tuple[int, Decimal]:
    """Return (ride_count, total_spend) for the user in the current month."""
    result = await db.execute(
        select(
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.rider_id == user_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= month_start,
        )
    )
    row = result.one()
    return row.rides or 0, Decimal(str(row.spend or 0))


async def _ytd_spend_for_user(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    year_start: date,
) -> tuple[int, Decimal]:
    """Return (ride_count, total_spend) for the user year-to-date."""
    result = await db.execute(
        select(
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.rider_id == user_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= year_start,
        )
    )
    row = result.one()
    return row.rides or 0, Decimal(str(row.spend or 0))


# ---------------------------------------------------------------------------
# Public: employee self-service
# ---------------------------------------------------------------------------


async def get_my_spend_summary(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> MySpendSummaryResponse:
    """Return the authenticated employee's current-month spend and limit info.

    Any active member may call this for their own data.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting employee.

    Returns:
        MySpendSummaryResponse with current-month and YTD figures.

    Raises:
        HTTP 403: When the user is not an active member.
    """
    member = await _require_active_member(db, account_id, user_id)

    now = _now_utc()
    month_start = date(now.year, now.month, 1)
    year_start = date(now.year, 1, 1)
    month = _month_str(now)

    cm_rides, cm_spend = await _current_month_spend_for_user(
        db, account_id, user_id, month_start
    )
    ytd_rides, ytd_spend = await _ytd_spend_for_user(
        db, account_id, user_id, year_start
    )

    limit: Decimal | None = member.monthly_spend_limit

    return MySpendSummaryResponse(
        account_id=account_id,
        user_id=user_id,
        current_month=month,
        current_month_rides=cm_rides,
        current_month_spend=cm_spend,
        monthly_spend_limit=limit,
        limit_utilization_pct=_utilization_pct(cm_spend, limit),
        ytd_rides=ytd_rides,
        ytd_spend=ytd_spend,
    )


async def get_my_spend_history(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    months: int = 6,
) -> MySpendHistoryResponse:
    """Return the authenticated employee's monthly spend trend.

    Any active member may call this for their own data.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting employee.
        months: Number of past months to include (1–24, default 6).

    Returns:
        MySpendHistoryResponse with data points ordered newest-first.

    Raises:
        HTTP 400: When months is out of range.
        HTTP 403: When the user is not an active member.
    """
    if not (1 <= months <= 24):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="months must be between 1 and 24.",
        )

    await _require_active_member(db, account_id, user_id)

    month_col = func.to_char(Ride.completed_at, "YYYY-MM").label("month")
    q = (
        select(
            month_col,
            func.count(Ride.id).label("total_rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend"),
        )
        .where(
            Ride.corporate_account_id == account_id,
            Ride.rider_id == user_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
        )
        .group_by(func.to_char(Ride.completed_at, "YYYY-MM"))
        .order_by(func.to_char(Ride.completed_at, "YYYY-MM").desc())
        .limit(months)
    )
    result = await db.execute(q)
    rows = result.all()

    data: list[MySpendHistoryPoint] = []
    for row in rows:
        total_rides = row.total_rides or 0
        total_spend = Decimal(str(row.total_spend or 0))
        data.append(
            MySpendHistoryPoint(
                month=row.month,
                total_rides=total_rides,
                total_spend=total_spend,
                avg_fare=_safe_avg(total_spend, total_rides),
            )
        )

    return MySpendHistoryResponse(
        account_id=account_id,
        user_id=user_id,
        months_requested=months,
        data=data,
    )


# ---------------------------------------------------------------------------
# Public: admin member views
# ---------------------------------------------------------------------------


async def get_member_spend_summary(
    db: AsyncSession,
    account_id: int,
    target_user_id: int,
    requesting_user_id: int,
) -> MemberSpendSummaryResponse:
    """Return a single member's spend summary (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        target_user_id: The member whose summary to return.
        requesting_user_id: The admin making the request.

    Returns:
        MemberSpendSummaryResponse with current-month and YTD figures.

    Raises:
        HTTP 403: When the requester is not an admin.
        HTTP 404: When the target member is not found in the account.
    """
    await _require_admin(db, account_id, requesting_user_id)
    member = await _fetch_target_member(db, account_id, target_user_id)

    now = _now_utc()
    month_start = date(now.year, now.month, 1)
    year_start = date(now.year, 1, 1)

    cm_rides, cm_spend = await _current_month_spend_for_user(
        db, account_id, target_user_id, month_start
    )
    ytd_rides, ytd_spend = await _ytd_spend_for_user(
        db, account_id, target_user_id, year_start
    )

    limit: Decimal | None = member.monthly_spend_limit

    return MemberSpendSummaryResponse(
        account_id=account_id,
        user_id=target_user_id,
        current_month=_month_str(now),
        current_month_rides=cm_rides,
        current_month_spend=cm_spend,
        monthly_spend_limit=limit,
        limit_utilization_pct=_utilization_pct(cm_spend, limit),
        ytd_rides=ytd_rides,
        ytd_spend=ytd_spend,
        is_active=member.is_active,
    )


async def list_members_spend_summary(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
) -> MemberSpendLimitsResponse:
    """Return all members with their spend limits and current-month usage.

    Only account admins may call this function.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        requesting_user_id: The admin making the request.

    Returns:
        MemberSpendLimitsResponse with one item per member.

    Raises:
        HTTP 403: When the requester is not an admin.
    """
    await _require_admin(db, account_id, requesting_user_id)

    now = _now_utc()
    month_start = date(now.year, now.month, 1)
    month = _month_str(now)

    # Fetch all members for the account
    members_result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id
        ).order_by(BusinessAccountMember.id)
    )
    members: Sequence[BusinessAccountMember] = members_result.scalars().all()

    if not members:
        return MemberSpendLimitsResponse(
            account_id=account_id,
            current_month=month,
            members=[],
        )

    user_ids = [m.user_id for m in members]

    # Bulk fetch current-month spend for all members in one query
    spend_result = await db.execute(
        select(
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


# ---------------------------------------------------------------------------
# Public: admin limit management
# ---------------------------------------------------------------------------


async def set_member_spend_limit(
    db: AsyncSession,
    account_id: int,
    target_user_id: int,
    requesting_user_id: int,
    monthly_limit_usd: Decimal,
) -> SpendLimitResponse:
    """Set or update the monthly spend limit for an account member.

    Only account admins may call this function.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        target_user_id: The member whose limit to set.
        requesting_user_id: The admin making the request.
        monthly_limit_usd: New monthly cap in USD (must be positive).

    Returns:
        SpendLimitResponse confirming the new limit.

    Raises:
        HTTP 400: When monthly_limit_usd is not positive.
        HTTP 403: When the requester is not an admin.
        HTTP 404: When the target member is not found.
    """
    if monthly_limit_usd <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="monthly_limit_usd must be a positive value.",
        )

    await _require_admin(db, account_id, requesting_user_id)
    member = await _fetch_target_member(db, account_id, target_user_id)

    member.monthly_spend_limit = monthly_limit_usd
    await db.flush()

    return SpendLimitResponse(
        account_id=account_id,
        user_id=target_user_id,
        monthly_spend_limit=monthly_limit_usd,
        message=f"Monthly spend limit set to ${monthly_limit_usd:.2f}.",
    )


async def remove_member_spend_limit(
    db: AsyncSession,
    account_id: int,
    target_user_id: int,
    requesting_user_id: int,
) -> SpendLimitResponse:
    """Remove the monthly spend limit for an account member (set to NULL).

    Only account admins may call this function.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        target_user_id: The member whose limit to remove.
        requesting_user_id: The admin making the request.

    Returns:
        SpendLimitResponse with monthly_spend_limit=None.

    Raises:
        HTTP 403: When the requester is not an admin.
        HTTP 404: When the target member is not found.
    """
    await _require_admin(db, account_id, requesting_user_id)
    member = await _fetch_target_member(db, account_id, target_user_id)

    member.monthly_spend_limit = None
    await db.flush()

    return SpendLimitResponse(
        account_id=account_id,
        user_id=target_user_id,
        monthly_spend_limit=None,
        message="Monthly spend limit removed.",
    )
