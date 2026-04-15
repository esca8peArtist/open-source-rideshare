"""Service layer for Corporate Carbon Budget & ESG Reporting.

Provides carbon footprint tracking and ESG (Environmental, Social, Governance)
reporting for corporate accounts.  Ride carbon data comes from the existing
ride_carbon_records table; this module adds budget configuration and aggregated
reporting on top of it.

Public surface
--------------
get_or_create_carbon_budget(db, account_id) -> CarbonBudgetResponse
update_carbon_budget(db, account_id, data, admin_id) -> CarbonBudgetResponse
get_account_carbon_summary(db, account_id, requesting_user_id) -> CarbonSummaryResponse
get_carbon_trend(db, account_id, requesting_user_id, months) -> CarbonTrendResponse
get_employee_carbon_breakdown(db, account_id, requesting_user_id, period_start, period_end) -> EmployeeCarbonBreakdownResponse
get_platform_esg_report(db, months) -> ESGReportResponse
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount, BusinessAccountMember, MemberRole
from app.models.corporate_carbon_budget import CorporateCarbonBudget
from app.models.ride import Ride
from app.models.ride_carbon import RideCarbonRecord, VehicleEmissionClass
from app.schemas.corporate_carbon_budget import (
    CarbonBudgetResponse,
    CarbonBudgetUpsert,
    CarbonSummaryResponse,
    CarbonTrendPoint,
    CarbonTrendResponse,
    EmployeeCarbonBreakdownResponse,
    EmployeeCarbonItem,
    ESGMonthPoint,
    ESGReportResponse,
)

# Emission classes counted as "green"
_GREEN_CLASSES = [VehicleEmissionClass.hybrid, VehicleEmissionClass.electric]

# Cents-to-USD conversion
_CENTS_TO_USD = Decimal("0.01")

# CO2 grams-to-kg conversion
_GRAMS_TO_KG = Decimal("0.001")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_budget_response(budget: CorporateCarbonBudget) -> CarbonBudgetResponse:
    """Convert model instance to CarbonBudgetResponse."""
    return CarbonBudgetResponse(
        id=budget.id,
        account_id=budget.account_id,
        monthly_budget_co2_kg=budget.monthly_budget_co2_kg,
        offset_budget_usd=budget.offset_budget_usd,
        tracking_enabled=budget.tracking_enabled,
        alert_threshold_pct=budget.alert_threshold_pct,
        notes=budget.notes,
        updated_by_id=budget.updated_by_id,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


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


def _safe_pct(numerator: int, denominator: int) -> Decimal:
    """Return percentage rounded to 2 d.p., or Decimal('0') when denominator is 0."""
    if denominator == 0:
        return Decimal("0.00")
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _cents_to_usd(cents: int) -> Decimal:
    """Convert integer cents to USD Decimal rounded to 2 d.p."""
    return (Decimal(cents) * _CENTS_TO_USD).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _grams_to_kg(grams: int) -> Decimal:
    """Convert integer grams to kg Decimal rounded to 3 d.p."""
    return (Decimal(grams) * _GRAMS_TO_KG).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )


# ---------------------------------------------------------------------------
# Budget configuration
# ---------------------------------------------------------------------------


async def get_or_create_carbon_budget(
    db: AsyncSession,
    account_id: int,
) -> CarbonBudgetResponse:
    """Return the carbon budget for an account, creating a default if absent.

    Follows the upsert-on-read pattern used by billing settings and notification
    configs — the first GET creates a row with default values so callers always
    receive a well-formed response.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Returns:
        CarbonBudgetResponse (existing or newly created default).
    """
    result = await db.execute(
        select(CorporateCarbonBudget).where(
            CorporateCarbonBudget.account_id == account_id
        )
    )
    budget = result.scalar_one_or_none()

    if budget is None:
        budget = CorporateCarbonBudget(
            account_id=account_id,
            monthly_budget_co2_kg=None,
            offset_budget_usd=None,
            tracking_enabled=True,
            alert_threshold_pct=80,
            notes=None,
            updated_by_id=None,
        )
        db.add(budget)
        await db.commit()
        await db.refresh(budget)

    return _to_budget_response(budget)


async def update_carbon_budget(
    db: AsyncSession,
    account_id: int,
    data: CarbonBudgetUpsert,
    admin_id: int,
) -> CarbonBudgetResponse:
    """Create or update the carbon budget configuration for an account.

    Follows PUT semantics: unset fields in the payload are ignored (only
    explicitly supplied values are written).  Creates the row if absent.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        data:       Validated upsert payload.
        admin_id:   ID of the admin making the change (audit trail).

    Returns:
        Updated CarbonBudgetResponse.
    """
    result = await db.execute(
        select(CorporateCarbonBudget).where(
            CorporateCarbonBudget.account_id == account_id
        )
    )
    budget = result.scalar_one_or_none()

    if budget is None:
        budget = CorporateCarbonBudget(
            account_id=account_id,
            tracking_enabled=True,
            alert_threshold_pct=80,
        )
        db.add(budget)

    # Apply only the fields that were explicitly set in the payload
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(budget, field, value)

    budget.updated_by_id = admin_id
    await db.commit()
    await db.refresh(budget)
    return _to_budget_response(budget)


# ---------------------------------------------------------------------------
# Carbon summary
# ---------------------------------------------------------------------------


async def get_account_carbon_summary(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
) -> CarbonSummaryResponse:
    """Return the current-month carbon footprint summary for an account.

    Any active member may call this when tracking_enabled is True.  Admins
    always see the data regardless of the tracking flag.

    Args:
        db:                  Async database session.
        account_id:          Corporate account identifier.
        requesting_user_id:  ID of the authenticated user.

    Returns:
        CarbonSummaryResponse aggregated over the current calendar month.

    Raises:
        HTTP 403: When the user is not a member, or tracking is disabled for
                  non-admin members.
    """
    member = await _require_account_member(db, account_id, requesting_user_id)

    # Fetch budget config (creates default if absent)
    budget = await get_or_create_carbon_budget(db, account_id)

    # Non-admins cannot view carbon data when tracking is disabled
    if not budget.tracking_enabled and member.role != MemberRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Carbon tracking is not enabled for this account.",
        )

    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    # Determine the start of next month for exclusive upper bound
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

    green_expr = case(
        (RideCarbonRecord.emission_class.in_(_GREEN_CLASSES), 1), else_=0
    )
    offset_rides_expr = case(
        (RideCarbonRecord.offset_paid.is_(True), 1), else_=0
    )
    offset_cents_expr = case(
        (RideCarbonRecord.offset_paid.is_(True), RideCarbonRecord.offset_amount_cents),
        else_=0,
    )

    q = (
        select(
            func.count(Ride.id).label("total_rides"),
            func.coalesce(func.sum(RideCarbonRecord.co2_grams), 0).label("total_co2_grams"),
            func.coalesce(func.sum(green_expr), 0).label("green_rides"),
            func.coalesce(func.sum(offset_rides_expr), 0).label("offset_paid_rides"),
            func.coalesce(func.sum(offset_cents_expr), 0).label("offset_paid_cents"),
        )
        .join(RideCarbonRecord, RideCarbonRecord.ride_id == Ride.id)
        .where(
            Ride.corporate_account_id == account_id,
            Ride.completed_at.is_not(None),
            Ride.completed_at >= month_start,
            Ride.completed_at < month_end,
        )
    )
    row = (await db.execute(q)).one()

    total_rides = row.total_rides or 0
    total_co2_kg = _grams_to_kg(row.total_co2_grams or 0)
    green_rides = row.green_rides or 0
    offset_paid_rides = row.offset_paid_rides or 0
    total_offset_usd = _cents_to_usd(row.offset_paid_cents or 0)
    green_pct = _safe_pct(green_rides, total_rides)

    # Budget utilisation
    budget_used_pct: Decimal | None = None
    alert_triggered = False
    if budget.monthly_budget_co2_kg is not None and budget.monthly_budget_co2_kg > 0:
        budget_used_pct = (
            total_co2_kg / Decimal(str(budget.monthly_budget_co2_kg)) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        alert_triggered = budget_used_pct >= Decimal(str(budget.alert_threshold_pct))

    return CarbonSummaryResponse(
        account_id=account_id,
        month=month_str,
        total_rides=total_rides,
        total_co2_kg=total_co2_kg,
        green_rides=green_rides,
        green_ride_pct=green_pct,
        offset_paid_rides=offset_paid_rides,
        total_offset_paid_usd=total_offset_usd,
        monthly_budget_co2_kg=budget.monthly_budget_co2_kg,
        budget_used_pct=budget_used_pct,
        alert_triggered=alert_triggered,
        tracking_enabled=budget.tracking_enabled,
    )


# ---------------------------------------------------------------------------
# Carbon trend
# ---------------------------------------------------------------------------


async def get_carbon_trend(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    months: int = 6,
) -> CarbonTrendResponse:
    """Return month-over-month carbon trend data for the last N months.

    Any active member may call this when tracking_enabled is True.

    Args:
        db:                  Async database session.
        account_id:          Corporate account identifier.
        requesting_user_id:  ID of the authenticated user.
        months:              Number of past months to include (1–24).

    Returns:
        CarbonTrendResponse with points ordered newest-first.

    Raises:
        HTTP 400: When months is out of range.
        HTTP 403: When the user is not a member or tracking is disabled.
    """
    if not (1 <= months <= 24):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="months must be between 1 and 24.",
        )

    member = await _require_account_member(db, account_id, requesting_user_id)
    budget = await get_or_create_carbon_budget(db, account_id)

    if not budget.tracking_enabled and member.role != MemberRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Carbon tracking is not enabled for this account.",
        )

    month_col = func.to_char(Ride.completed_at, "YYYY-MM").label("month")
    green_expr = case(
        (RideCarbonRecord.emission_class.in_(_GREEN_CLASSES), 1), else_=0
    )
    offset_cents_expr = case(
        (RideCarbonRecord.offset_paid.is_(True), RideCarbonRecord.offset_amount_cents),
        else_=0,
    )

    q = (
        select(
            month_col,
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(RideCarbonRecord.co2_grams), 0).label("co2_grams"),
            func.coalesce(func.sum(green_expr), 0).label("green_rides"),
            func.coalesce(func.sum(offset_cents_expr), 0).label("offset_cents"),
        )
        .join(RideCarbonRecord, RideCarbonRecord.ride_id == Ride.id)
        .where(
            Ride.corporate_account_id == account_id,
            Ride.completed_at.is_not(None),
        )
        .group_by(func.to_char(Ride.completed_at, "YYYY-MM"))
        .order_by(func.to_char(Ride.completed_at, "YYYY-MM").desc())
        .limit(months)
    )
    rows = (await db.execute(q)).all()

    data: list[CarbonTrendPoint] = [
        CarbonTrendPoint(
            month=row.month,
            rides=row.rides or 0,
            co2_kg=_grams_to_kg(row.co2_grams or 0),
            green_rides=row.green_rides or 0,
            offset_paid_usd=_cents_to_usd(row.offset_cents or 0),
        )
        for row in rows
    ]

    return CarbonTrendResponse(
        account_id=account_id,
        months_requested=months,
        data=data,
    )


# ---------------------------------------------------------------------------
# Employee carbon breakdown
# ---------------------------------------------------------------------------


async def get_employee_carbon_breakdown(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    period_start: date,
    period_end: date,
) -> EmployeeCarbonBreakdownResponse:
    """Return per-employee carbon footprint for a billing period.

    Admin-only endpoint.  Ordered by co2_kg descending (highest emitters
    first) for use in sustainability coaching.

    Args:
        db:                  Async database session.
        account_id:          Corporate account identifier.
        requesting_user_id:  ID of the authenticated user (must be admin).
        period_start:        Inclusive start of the analysis period.
        period_end:          Inclusive end of the analysis period.

    Returns:
        EmployeeCarbonBreakdownResponse with per-employee list and totals.

    Raises:
        HTTP 400: When period_end precedes period_start.
        HTTP 403: When the user is not an account admin.
    """
    if period_end < period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must not be before period_start.",
        )

    await _require_account_admin(db, account_id, requesting_user_id)

    green_expr = case(
        (RideCarbonRecord.emission_class.in_(_GREEN_CLASSES), 1), else_=0
    )
    offset_cents_expr = case(
        (RideCarbonRecord.offset_paid.is_(True), RideCarbonRecord.offset_amount_cents),
        else_=0,
    )

    q = (
        select(
            Ride.rider_id.label("user_id"),
            func.count(Ride.id).label("rides"),
            func.coalesce(func.sum(RideCarbonRecord.co2_grams), 0).label("co2_grams"),
            func.coalesce(func.sum(green_expr), 0).label("green_rides"),
            func.coalesce(func.sum(offset_cents_expr), 0).label("offset_cents"),
        )
        .join(RideCarbonRecord, RideCarbonRecord.ride_id == Ride.id)
        .where(
            Ride.corporate_account_id == account_id,
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= period_start,
            func.date(Ride.completed_at) <= period_end,
        )
        .group_by(Ride.rider_id)
        .order_by(func.sum(RideCarbonRecord.co2_grams).desc())
    )
    rows = (await db.execute(q)).all()

    employees: list[EmployeeCarbonItem] = [
        EmployeeCarbonItem(
            user_id=row.user_id,
            rides=row.rides or 0,
            co2_kg=_grams_to_kg(row.co2_grams or 0),
            green_rides=row.green_rides or 0,
            offset_paid_usd=_cents_to_usd(row.offset_cents or 0),
        )
        for row in rows
    ]

    account_total_co2 = sum(e.co2_kg for e in employees)
    account_total_rides = sum(e.rides for e in employees)

    return EmployeeCarbonBreakdownResponse(
        account_id=account_id,
        period_start=period_start,
        period_end=period_end,
        account_total_co2_kg=account_total_co2,
        account_total_rides=account_total_rides,
        employees=employees,
    )


# ---------------------------------------------------------------------------
# Platform ESG report (platform-admin only)
# ---------------------------------------------------------------------------


async def get_platform_esg_report(
    db: AsyncSession,
    months: int = 12,
) -> ESGReportResponse:
    """Return a platform-wide ESG carbon summary across all corporate accounts.

    Platform-admin only.  Aggregates ride_carbon_records for all rides that
    are billed to a corporate account and groups the data by calendar month.

    Args:
        db:     Async database session.
        months: Number of past calendar months to include (1–24, default 12).

    Returns:
        ESGReportResponse with cumulative totals and monthly trend.

    Raises:
        HTTP 400: When months is out of range.
    """
    if not (1 <= months <= 24):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="months must be between 1 and 24.",
        )

    month_col = func.to_char(Ride.completed_at, "YYYY-MM").label("month")
    green_expr = case(
        (RideCarbonRecord.emission_class.in_(_GREEN_CLASSES), 1), else_=0
    )
    offset_cents_expr = case(
        (RideCarbonRecord.offset_paid.is_(True), RideCarbonRecord.offset_amount_cents),
        else_=0,
    )

    q = (
        select(
            month_col,
            func.count(Ride.id).label("total_rides"),
            func.coalesce(func.sum(RideCarbonRecord.co2_grams), 0).label("co2_grams"),
            func.coalesce(func.sum(green_expr), 0).label("green_rides"),
            func.coalesce(func.sum(offset_cents_expr), 0).label("offset_cents"),
            func.count(func.distinct(Ride.corporate_account_id)).label("active_accounts"),
        )
        .join(RideCarbonRecord, RideCarbonRecord.ride_id == Ride.id)
        .where(
            Ride.corporate_account_id.is_not(None),
            Ride.completed_at.is_not(None),
        )
        .group_by(func.to_char(Ride.completed_at, "YYYY-MM"))
        .order_by(func.to_char(Ride.completed_at, "YYYY-MM").desc())
        .limit(months)
    )
    rows = (await db.execute(q)).all()

    trend: list[ESGMonthPoint] = []
    for row in rows:
        rides = row.total_rides or 0
        green = row.green_rides or 0
        co2_kg = _grams_to_kg(row.co2_grams or 0)
        offset_usd = _cents_to_usd(row.offset_cents or 0)
        trend.append(
            ESGMonthPoint(
                month=row.month,
                total_rides=rides,
                total_co2_kg=co2_kg,
                green_rides=green,
                green_ride_pct=_safe_pct(green, rides),
                total_offset_paid_usd=offset_usd,
                active_corporate_accounts=row.active_accounts or 0,
            )
        )

    # Cumulative totals across all returned months
    cumulative_rides = sum(p.total_rides for p in trend)
    cumulative_co2 = sum(p.total_co2_kg for p in trend)
    cumulative_green = sum(p.green_rides for p in trend)
    cumulative_offset = sum(p.total_offset_paid_usd for p in trend)
    overall_green_pct = _safe_pct(cumulative_green, cumulative_rides)

    return ESGReportResponse(
        months_requested=months,
        cumulative_co2_kg=cumulative_co2,
        cumulative_green_rides=cumulative_green,
        cumulative_rides=cumulative_rides,
        cumulative_offset_paid_usd=cumulative_offset,
        overall_green_pct=overall_green_pct,
        monthly_trend=trend,
    )
