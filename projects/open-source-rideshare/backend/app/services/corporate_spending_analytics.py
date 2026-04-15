"""Service layer for Corporate Spending Analytics.

Provides read-only analytics over completed corporate rides: spending
overviews, month-over-month trends, per-employee breakdowns, and
ride pattern analysis (by hour-of-day and day-of-week).

All functions enforce that the requesting user is an active member of the
target corporate account.  Employee breakdown additionally requires admin
role, as it exposes individual spending data.

Public surface
--------------
get_spending_overview(db, account_id, requesting_user_id)
get_monthly_spend_trend(db, account_id, requesting_user_id, months=12)
get_employee_spend_breakdown(db, account_id, requesting_user_id, period_start, period_end, limit=10)
get_ride_pattern_analytics(db, account_id, requesting_user_id, period_start, period_end)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount, BusinessAccountMember, MemberRole
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_spending_analytics import (
    DayBucket,
    EmployeeSpendBreakdownResponse,
    EmployeeSpendItem,
    HourBucket,
    MonthlySpendPoint,
    MonthlySpendTrendResponse,
    RidePatternResponse,
    SpendingOverviewResponse,
)

# Day-of-week name lookup indexed by PostgreSQL's extract('dow', …) result.
# PostgreSQL returns 0=Sunday, 1=Monday … 6=Saturday.
_DOW_NAMES = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active member of the account."""
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


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active admin of the account."""
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


def _safe_avg(total_spend: Decimal, total_rides: int) -> Decimal | None:
    """Return average fare rounded to 2 d.p., or None if no rides."""
    if total_rides == 0:
        return None
    return (total_spend / total_rides).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Public: spending overview
# ---------------------------------------------------------------------------


async def get_spending_overview(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
) -> SpendingOverviewResponse:
    """Return current-month, YTD, and all-time spend totals for the account.

    Any active member may call this function.

    Args:
        db: Database session.
        account_id: Corporate account identifier (corporate_accounts_v2.id).
        requesting_user_id: ID of the authenticated user.

    Returns:
        SpendingOverviewResponse with aggregated counters and optional
        budget utilisation percentage.

    Raises:
        HTTP 403: When the user is not an active member.
    """
    await _require_account_member(db, account_id, requesting_user_id)

    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")
    month_start = date(now.year, now.month, 1)
    year_start = date(now.year, 1, 1)

    # Current month aggregate
    cm_result = await db.execute(
        select(
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= month_start,
        )
    )
    cm_row = cm_result.one()
    current_month_rides = cm_row.rides or 0
    current_month_spend = Decimal(str(cm_row.spend or 0))

    # Year-to-date aggregate
    ytd_result = await db.execute(
        select(
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= year_start,
        )
    )
    ytd_row = ytd_result.one()
    ytd_rides = ytd_row.rides or 0
    ytd_spend = Decimal(str(ytd_row.spend or 0))

    # All-time aggregate
    at_result = await db.execute(
        select(
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
        )
    )
    at_row = at_result.one()
    all_time_rides = at_row.rides or 0
    all_time_spend = Decimal(str(at_row.spend or 0))

    # Monthly budget limit from account record
    acct_result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == account_id)
    )
    account = acct_result.scalar_one_or_none()
    budget_limit: Decimal | None = account.monthly_budget_limit if account else None

    budget_utilization: float | None = None
    if budget_limit is not None and budget_limit > 0:
        budget_utilization = float(
            (current_month_spend / budget_limit * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )

    return SpendingOverviewResponse(
        account_id=account_id,
        current_month=month_str,
        current_month_rides=current_month_rides,
        current_month_spend=current_month_spend,
        ytd_rides=ytd_rides,
        ytd_spend=ytd_spend,
        all_time_rides=all_time_rides,
        all_time_spend=all_time_spend,
        monthly_budget_limit=budget_limit,
        current_month_budget_utilization_pct=budget_utilization,
    )


# ---------------------------------------------------------------------------
# Public: monthly spend trend
# ---------------------------------------------------------------------------


async def get_monthly_spend_trend(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    months: int = 12,
) -> MonthlySpendTrendResponse:
    """Return monthly spend data points for the last N calendar months.

    Any active member may call this function.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user.
        months: Number of past months to include (1–24, default 12).

    Returns:
        MonthlySpendTrendResponse with data points ordered newest-first.

    Raises:
        HTTP 400: When months is out of range.
        HTTP 403: When the user is not an active member.
    """
    if not (1 <= months <= 24):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="months must be between 1 and 24.",
        )

    await _require_account_member(db, account_id, requesting_user_id)

    # Group completed rides by calendar month using PostgreSQL's to_char.
    # The label aliases are accessed on the result rows by name.
    month_col = func.to_char(Ride.completed_at, "YYYY-MM").label("month")
    q = (
        select(
            month_col,
            func.count(Ride.id).label("total_rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend"),
        )
        .where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
        )
        .group_by(func.to_char(Ride.completed_at, "YYYY-MM"))
        .order_by(func.to_char(Ride.completed_at, "YYYY-MM").desc())
        .limit(months)
    )
    result = await db.execute(q)
    rows = result.all()

    data: list[MonthlySpendPoint] = []
    for row in rows:
        total_rides = row.total_rides or 0
        total_spend = Decimal(str(row.total_spend or 0))
        data.append(
            MonthlySpendPoint(
                month=row.month,
                total_rides=total_rides,
                total_spend=total_spend,
                avg_fare=_safe_avg(total_spend, total_rides),
            )
        )

    return MonthlySpendTrendResponse(
        account_id=account_id,
        months_requested=months,
        data=data,
    )


# ---------------------------------------------------------------------------
# Public: employee spend breakdown
# ---------------------------------------------------------------------------


async def get_employee_spend_breakdown(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    period_start: date,
    period_end: date,
    limit: int = 10,
) -> EmployeeSpendBreakdownResponse:
    """Return the top spenders (by total spend) within a billing period.

    Only account admins may call this function, as it exposes individual
    employee spending data.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user (must be admin).
        period_start: Inclusive start of the analysis window.
        period_end: Inclusive end of the analysis window.
        limit: Maximum number of employees to return (1–50, default 10).

    Returns:
        EmployeeSpendBreakdownResponse with top_spenders list.

    Raises:
        HTTP 400: When period_end precedes period_start, or limit out of range.
        HTTP 403: When the user is not an account admin.
    """
    if period_end < period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must not be before period_start.",
        )
    if not (1 <= limit <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 50.",
        )

    await _require_account_admin(db, account_id, requesting_user_id)

    q = (
        select(
            Ride.rider_id.label("user_id"),
            func.count(Ride.id).label("total_rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend"),
        )
        .where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= period_start,
            func.date(Ride.completed_at) <= period_end,
        )
        .group_by(Ride.rider_id)
        .order_by(func.sum(Ride.actual_fare).desc())
        .limit(limit)
    )
    result = await db.execute(q)
    rows = result.all()

    top_spenders: list[EmployeeSpendItem] = []
    for row in rows:
        total_rides = row.total_rides or 0
        total_spend = Decimal(str(row.total_spend or 0))
        top_spenders.append(
            EmployeeSpendItem(
                user_id=row.user_id,
                total_rides=total_rides,
                total_spend=total_spend,
                avg_fare=_safe_avg(total_spend, total_rides),
            )
        )

    return EmployeeSpendBreakdownResponse(
        account_id=account_id,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        top_spenders=top_spenders,
    )


# ---------------------------------------------------------------------------
# Public: ride pattern analytics
# ---------------------------------------------------------------------------


async def get_ride_pattern_analytics(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    period_start: date,
    period_end: date,
) -> RidePatternResponse:
    """Return ride distribution by hour-of-day and day-of-week.

    Any active member may call this function.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user.
        period_start: Inclusive start of the analysis window.
        period_end: Inclusive end of the analysis window.

    Returns:
        RidePatternResponse with fully-populated by_hour (0–23) and
        by_day_of_week (0–6) buckets, including zero-count buckets.

    Raises:
        HTTP 400: When period_end precedes period_start.
        HTTP 403: When the user is not an active member.
    """
    if period_end < period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must not be before period_start.",
        )

    await _require_account_member(db, account_id, requesting_user_id)

    base_where = [
        Ride.corporate_account_id == account_id,
        Ride.completed_at.is_not(None),
        func.date(Ride.completed_at) >= period_start,
        func.date(Ride.completed_at) <= period_end,
    ]

    # Hour-of-day breakdown
    hour_result = await db.execute(
        select(
            extract("hour", Ride.completed_at).label("hour"),
            func.count(Ride.id).label("ride_count"),
        )
        .where(*base_where)
        .group_by(extract("hour", Ride.completed_at))
        .order_by(extract("hour", Ride.completed_at))
    )
    hour_rows = hour_result.all()
    hour_map: dict[int, int] = {int(row.hour): row.ride_count for row in hour_rows}
    by_hour = [
        HourBucket(hour=h, ride_count=hour_map.get(h, 0)) for h in range(24)
    ]

    # Day-of-week breakdown (PostgreSQL extract('dow') → 0=Sun … 6=Sat)
    dow_result = await db.execute(
        select(
            extract("dow", Ride.completed_at).label("dow"),
            func.count(Ride.id).label("ride_count"),
        )
        .where(*base_where)
        .group_by(extract("dow", Ride.completed_at))
        .order_by(extract("dow", Ride.completed_at))
    )
    dow_rows = dow_result.all()
    dow_map: dict[int, int] = {int(row.dow): row.ride_count for row in dow_rows}
    by_day_of_week = [
        DayBucket(
            day_of_week=d,
            day_name=_DOW_NAMES[d],
            ride_count=dow_map.get(d, 0),
        )
        for d in range(7)
    ]

    total_rides = sum(b.ride_count for b in by_hour)

    return RidePatternResponse(
        account_id=account_id,
        period_start=period_start,
        period_end=period_end,
        total_rides=total_rides,
        by_hour=by_hour,
        by_day_of_week=by_day_of_week,
    )
