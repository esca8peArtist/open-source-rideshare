"""Service layer for Corporate Fleet Cost Analytics.

Aggregates fuel, maintenance, and toll costs per vehicle and per fleet,
with optional period filtering and monthly trend views.

All functions require the requesting user to be an active admin of the
target corporate account.

Public surface
--------------
get_fleet_cost_summary(db, account_id, user_id, start_date, end_date)
get_vehicle_cost_breakdown(db, account_id, user_id, start_date, end_date)
get_fleet_monthly_cost_trend(db, account_id, user_id, n_months)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import extract, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_fleet_fuel_log import CorporateFleetFuelLog
from app.models.corporate_fleet_maintenance import (
    CorporateFleetMaintenanceRecord,
    FleetMaintenanceStatus,
)
from app.models.corporate_fleet_toll import CorporateFleetTollCharge
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.schemas.corporate_fleet_cost_analytics import (
    FleetCostSummaryResponse,
    FleetMonthlyCostTrendResponse,
    MonthlyCostPoint,
    VehicleCostBreakdownResponse,
    VehicleCostItem,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public: fleet cost summary
# ---------------------------------------------------------------------------


async def get_fleet_cost_summary(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> FleetCostSummaryResponse:
    """Return aggregate fuel, maintenance, and toll costs for the fleet.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the authenticated user (must be admin).
        start_date: Inclusive start of the period filter, optional.
        end_date: Inclusive end of the period filter, optional.

    Returns:
        FleetCostSummaryResponse with totals broken down by cost category.

    Raises:
        HTTP 403: When the user is not an active admin.
    """
    await _require_account_admin(db, account_id, user_id)

    # ---- Fuel cost ----
    fuel_q = select(
        func.coalesce(func.sum(CorporateFleetFuelLog.total_cost_usd), 0).label("total")
    ).where(CorporateFleetFuelLog.account_id == account_id)
    if start_date is not None:
        fuel_q = fuel_q.where(CorporateFleetFuelLog.fill_date >= start_date)
    if end_date is not None:
        fuel_q = fuel_q.where(CorporateFleetFuelLog.fill_date <= end_date)
    fuel_result = await db.execute(fuel_q)
    fuel_cost = Decimal(str(fuel_result.scalar_one() or 0))

    # ---- Maintenance cost (completed records only) ----
    maint_q = select(
        func.coalesce(
            func.sum(CorporateFleetMaintenanceRecord.cost_usd), 0
        ).label("total")
    ).where(
        CorporateFleetMaintenanceRecord.account_id == account_id,
        CorporateFleetMaintenanceRecord.status == FleetMaintenanceStatus.completed,
    )
    if start_date is not None:
        maint_q = maint_q.where(
            CorporateFleetMaintenanceRecord.completed_date >= start_date
        )
    if end_date is not None:
        maint_q = maint_q.where(
            CorporateFleetMaintenanceRecord.completed_date <= end_date
        )
    maint_result = await db.execute(maint_q)
    maint_cost = Decimal(str(maint_result.scalar_one() or 0))

    # ---- Toll cost ----
    toll_q = select(
        func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("total")
    ).where(CorporateFleetTollCharge.account_id == account_id)
    if start_date is not None:
        toll_q = toll_q.where(CorporateFleetTollCharge.charge_date >= start_date)
    if end_date is not None:
        toll_q = toll_q.where(CorporateFleetTollCharge.charge_date <= end_date)
    toll_result = await db.execute(toll_q)
    toll_cost = Decimal(str(toll_result.scalar_one() or 0))

    # ---- Vehicle count (distinct vehicles appearing in any cost table) ----
    fuel_vids = select(CorporateFleetFuelLog.fleet_vehicle_id).where(
        CorporateFleetFuelLog.account_id == account_id
    )
    maint_vids = select(CorporateFleetMaintenanceRecord.fleet_vehicle_id).where(
        CorporateFleetMaintenanceRecord.account_id == account_id
    )
    toll_vids = select(CorporateFleetTollCharge.fleet_vehicle_id).where(
        CorporateFleetTollCharge.account_id == account_id
    )
    combined = union(fuel_vids, maint_vids, toll_vids).subquery()
    count_result = await db.execute(
        select(func.count()).select_from(combined)
    )
    vehicle_count = count_result.scalar_one() or 0

    total_cost = fuel_cost + maint_cost + toll_cost

    return FleetCostSummaryResponse(
        account_id=account_id,
        period_start=start_date,
        period_end=end_date,
        total_fuel_cost_usd=fuel_cost,
        total_maintenance_cost_usd=maint_cost,
        total_toll_cost_usd=toll_cost,
        total_cost_usd=total_cost,
        vehicle_count=vehicle_count,
    )


# ---------------------------------------------------------------------------
# Public: vehicle cost breakdown
# ---------------------------------------------------------------------------


async def get_vehicle_cost_breakdown(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> VehicleCostBreakdownResponse:
    """Return per-vehicle cost breakdown for the fleet.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the authenticated user (must be admin).
        start_date: Inclusive start of the period filter, optional.
        end_date: Inclusive end of the period filter, optional.

    Returns:
        VehicleCostBreakdownResponse with a VehicleCostItem per vehicle.

    Raises:
        HTTP 403: When the user is not an active admin.
    """
    await _require_account_admin(db, account_id, user_id)

    # Fetch all vehicles for the account
    vehicles_result = await db.execute(
        select(CorporateFleetVehicle).where(
            CorporateFleetVehicle.account_id == account_id
        )
    )
    vehicles = vehicles_result.scalars().all()

    if not vehicles:
        return VehicleCostBreakdownResponse(
            account_id=account_id,
            period_start=start_date,
            period_end=end_date,
            vehicles=[],
        )

    # ---- Fuel costs per vehicle ----
    fuel_q = select(
        CorporateFleetFuelLog.fleet_vehicle_id,
        func.coalesce(func.sum(CorporateFleetFuelLog.total_cost_usd), 0).label("fuel_cost"),
    ).where(
        CorporateFleetFuelLog.account_id == account_id
    )
    if start_date is not None:
        fuel_q = fuel_q.where(CorporateFleetFuelLog.fill_date >= start_date)
    if end_date is not None:
        fuel_q = fuel_q.where(CorporateFleetFuelLog.fill_date <= end_date)
    fuel_q = fuel_q.group_by(CorporateFleetFuelLog.fleet_vehicle_id)
    fuel_result = await db.execute(fuel_q)
    fuel_map: dict = {row.fleet_vehicle_id: Decimal(str(row.fuel_cost or 0)) for row in fuel_result.all()}

    # ---- Maintenance costs per vehicle (completed only) ----
    maint_q = select(
        CorporateFleetMaintenanceRecord.fleet_vehicle_id,
        func.coalesce(func.sum(CorporateFleetMaintenanceRecord.cost_usd), 0).label("maint_cost"),
    ).where(
        CorporateFleetMaintenanceRecord.account_id == account_id,
        CorporateFleetMaintenanceRecord.status == FleetMaintenanceStatus.completed,
    )
    if start_date is not None:
        maint_q = maint_q.where(
            CorporateFleetMaintenanceRecord.completed_date >= start_date
        )
    if end_date is not None:
        maint_q = maint_q.where(
            CorporateFleetMaintenanceRecord.completed_date <= end_date
        )
    maint_q = maint_q.group_by(CorporateFleetMaintenanceRecord.fleet_vehicle_id)
    maint_result = await db.execute(maint_q)
    maint_map: dict = {row.fleet_vehicle_id: Decimal(str(row.maint_cost or 0)) for row in maint_result.all()}

    # ---- Toll costs per vehicle ----
    toll_q = select(
        CorporateFleetTollCharge.fleet_vehicle_id,
        func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("toll_cost"),
    ).where(
        CorporateFleetTollCharge.account_id == account_id
    )
    if start_date is not None:
        toll_q = toll_q.where(CorporateFleetTollCharge.charge_date >= start_date)
    if end_date is not None:
        toll_q = toll_q.where(CorporateFleetTollCharge.charge_date <= end_date)
    toll_q = toll_q.group_by(CorporateFleetTollCharge.fleet_vehicle_id)
    toll_result = await db.execute(toll_q)
    toll_map: dict = {row.fleet_vehicle_id: Decimal(str(row.toll_cost or 0)) for row in toll_result.all()}

    items: list[VehicleCostItem] = []
    for v in vehicles:
        fuel_cost = fuel_map.get(v.id, Decimal("0"))
        maint_cost = maint_map.get(v.id, Decimal("0"))
        toll_cost = toll_map.get(v.id, Decimal("0"))
        items.append(
            VehicleCostItem(
                vehicle_id=v.id,
                make=v.make or "",
                model=v.model_name or "",
                year=v.year or 0,
                license_plate=v.license_plate or "",
                fuel_cost_usd=fuel_cost,
                maintenance_cost_usd=maint_cost,
                toll_cost_usd=toll_cost,
                total_cost_usd=fuel_cost + maint_cost + toll_cost,
            )
        )

    return VehicleCostBreakdownResponse(
        account_id=account_id,
        period_start=start_date,
        period_end=end_date,
        vehicles=items,
    )


# ---------------------------------------------------------------------------
# Public: fleet monthly cost trend
# ---------------------------------------------------------------------------


async def get_fleet_monthly_cost_trend(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    n_months: int = 12,
) -> FleetMonthlyCostTrendResponse:
    """Return monthly aggregated costs for fuel, maintenance, and tolls.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the authenticated user (must be admin).
        n_months: Number of past months to include (1–36, default 12).

    Returns:
        FleetMonthlyCostTrendResponse with MonthlyCostPoint per month.

    Raises:
        HTTP 403: When the user is not an active admin.
    """
    await _require_account_admin(db, account_id, user_id)

    now = datetime.now(timezone.utc)

    # ---- Monthly fuel costs ----
    fuel_q = (
        select(
            extract("year", CorporateFleetFuelLog.fill_date).label("yr"),
            extract("month", CorporateFleetFuelLog.fill_date).label("mo"),
            func.coalesce(func.sum(CorporateFleetFuelLog.total_cost_usd), 0).label("fuel_cost"),
        )
        .where(CorporateFleetFuelLog.account_id == account_id)
        .group_by(
            extract("year", CorporateFleetFuelLog.fill_date),
            extract("month", CorporateFleetFuelLog.fill_date),
        )
    )
    fuel_result = await db.execute(fuel_q)
    fuel_monthly: dict[str, Decimal] = {}
    for row in fuel_result.all():
        key = f"{int(row.yr):04d}-{int(row.mo):02d}"
        fuel_monthly[key] = Decimal(str(row.fuel_cost or 0))

    # ---- Monthly maintenance costs (completed only) ----
    maint_q = (
        select(
            extract("year", CorporateFleetMaintenanceRecord.completed_date).label("yr"),
            extract("month", CorporateFleetMaintenanceRecord.completed_date).label("mo"),
            func.coalesce(func.sum(CorporateFleetMaintenanceRecord.cost_usd), 0).label("maint_cost"),
        )
        .where(
            CorporateFleetMaintenanceRecord.account_id == account_id,
            CorporateFleetMaintenanceRecord.status == FleetMaintenanceStatus.completed,
            CorporateFleetMaintenanceRecord.completed_date.is_not(None),
        )
        .group_by(
            extract("year", CorporateFleetMaintenanceRecord.completed_date),
            extract("month", CorporateFleetMaintenanceRecord.completed_date),
        )
    )
    maint_result = await db.execute(maint_q)
    maint_monthly: dict[str, Decimal] = {}
    for row in maint_result.all():
        key = f"{int(row.yr):04d}-{int(row.mo):02d}"
        maint_monthly[key] = Decimal(str(row.maint_cost or 0))

    # ---- Monthly toll costs ----
    toll_q = (
        select(
            extract("year", CorporateFleetTollCharge.charge_date).label("yr"),
            extract("month", CorporateFleetTollCharge.charge_date).label("mo"),
            func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("toll_cost"),
        )
        .where(CorporateFleetTollCharge.account_id == account_id)
        .group_by(
            extract("year", CorporateFleetTollCharge.charge_date),
            extract("month", CorporateFleetTollCharge.charge_date),
        )
    )
    toll_result = await db.execute(toll_q)
    toll_monthly: dict[str, Decimal] = {}
    for row in toll_result.all():
        key = f"{int(row.yr):04d}-{int(row.mo):02d}"
        toll_monthly[key] = Decimal(str(row.toll_cost or 0))

    # ---- Collect and sort months seen in any cost table ----
    all_months: set[str] = (
        set(fuel_monthly.keys()) | set(maint_monthly.keys()) | set(toll_monthly.keys())
    )
    sorted_months = sorted(all_months, reverse=True)[:n_months]
    sorted_months.sort()  # chronological order

    points: list[MonthlyCostPoint] = []
    for month_key in sorted_months:
        fuel_cost = fuel_monthly.get(month_key, Decimal("0"))
        maint_cost = maint_monthly.get(month_key, Decimal("0"))
        toll_cost = toll_monthly.get(month_key, Decimal("0"))
        points.append(
            MonthlyCostPoint(
                month=month_key,
                fuel_cost_usd=fuel_cost,
                maintenance_cost_usd=maint_cost,
                toll_cost_usd=toll_cost,
                total_cost_usd=fuel_cost + maint_cost + toll_cost,
            )
        )

    return FleetMonthlyCostTrendResponse(
        account_id=account_id,
        months=points,
    )
