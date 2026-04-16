"""Service layer for Corporate Fleet Fuel & Mileage Tracking.

Fleet managers and drivers log fuel fill-ups for company vehicles.  The
service exposes CRUD operations, per-vehicle summaries, and fleet-wide
fuel analytics.

Public functions
----------------
log_fuel_fill           — create a new fuel log entry for a fleet vehicle.
get_fuel_log            — fetch one fuel log by ID (404 if missing or wrong account).
update_fuel_log         — partial update on a fuel log record.
delete_fuel_log         — hard-delete a fuel log (admin use).
list_vehicle_fuel_logs  — all fuel logs for a vehicle, with optional filters.
get_vehicle_fuel_summary — per-vehicle fuel cost and efficiency analytics.
list_account_fuel_logs  — all fuel logs for an account, with optional filters.
get_fleet_fuel_summary  — fleet-wide fuel analytics for an account.
list_all_platform       — platform-admin: all logs, optional account filter.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_fuel_log import (
    CorporateFleetFuelLog,
    FleetFuelType,
)
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.schemas.corporate_fleet_fuel_log import (
    FleetFuelSummary,
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    FuelTypeBreakdown,
    VehicleFuelSummary,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateFleetFuelLog) -> FuelLogResponse:
    return FuelLogResponse(
        id=row.id,
        fleet_vehicle_id=row.fleet_vehicle_id,
        account_id=row.account_id,
        fuel_type=row.fuel_type.value if hasattr(row.fuel_type, "value") else str(row.fuel_type),
        fill_date=row.fill_date,
        odometer_miles=row.odometer_miles,
        gallons_added=float(row.gallons_added) if row.gallons_added is not None else None,
        kwh_added=float(row.kwh_added) if row.kwh_added is not None else None,
        cost_per_unit_usd=float(row.cost_per_unit_usd) if row.cost_per_unit_usd is not None else None,
        total_cost_usd=float(row.total_cost_usd) if row.total_cost_usd is not None else None,
        station_name=row.station_name,
        notes=row.notes,
        logged_by_id=row.logged_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == fleet_vehicle_id,
        CorporateFleetVehicle.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found for this account.",
        )
    return row


async def _fetch_log(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
) -> CorporateFleetFuelLog:
    """Return a fuel log record verifying account ownership.

    Raises:
        HTTPException 404: Fuel log not found or wrong account.
    """
    stmt = select(CorporateFleetFuelLog).where(
        CorporateFleetFuelLog.id == log_id,
        CorporateFleetFuelLog.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fuel log not found.",
        )
    return row


# ---------------------------------------------------------------------------
# log_fuel_fill
# ---------------------------------------------------------------------------


async def log_fuel_fill(
    db: AsyncSession,
    account_id: int,
    data: FuelLogCreate,
    logged_by_id: Optional[int] = None,
) -> FuelLogResponse:
    """Create a new fuel fill-up or energy charge log entry.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Fuel log creation payload (includes fleet_vehicle_id).
        logged_by_id: ID of the user creating the record.

    Returns:
        ``FuelLogResponse`` for the new record.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)

    log = CorporateFleetFuelLog(
        id=uuid.uuid4(),
        fleet_vehicle_id=data.fleet_vehicle_id,
        account_id=account_id,
        fuel_type=data.fuel_type,
        fill_date=data.fill_date,
        odometer_miles=data.odometer_miles,
        gallons_added=data.gallons_added,
        kwh_added=data.kwh_added,
        cost_per_unit_usd=data.cost_per_unit_usd,
        total_cost_usd=data.total_cost_usd,
        station_name=data.station_name,
        notes=data.notes,
        logged_by_id=logged_by_id,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _to_response(log)


# ---------------------------------------------------------------------------
# get_fuel_log
# ---------------------------------------------------------------------------


async def get_fuel_log(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
) -> FuelLogResponse:
    """Return a single fuel log record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the fuel log.

    Returns:
        ``FuelLogResponse``.

    Raises:
        HTTPException 404: Log not found or wrong account.
    """
    row = await _fetch_log(db, account_id, log_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# update_fuel_log
# ---------------------------------------------------------------------------


async def update_fuel_log(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
    data: FuelLogUpdate,
) -> FuelLogResponse:
    """Partially update a fuel log record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the fuel log.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``FuelLogResponse``.

    Raises:
        HTTPException 404: Log not found or wrong account.
    """
    row = await _fetch_log(db, account_id, log_id)
    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# delete_fuel_log
# ---------------------------------------------------------------------------


async def delete_fuel_log(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
) -> None:
    """Hard-delete a fuel log record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the fuel log.

    Raises:
        HTTPException 404: Log not found or wrong account.
    """
    row = await _fetch_log(db, account_id, log_id)
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# list_vehicle_fuel_logs
# ---------------------------------------------------------------------------


async def list_vehicle_fuel_logs(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    *,
    fuel_type: Optional[FleetFuelType] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[FuelLogResponse]:
    """Return all fuel logs for a fleet vehicle, with optional filters.

    Results are ordered by fill_date descending (most recent first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.
        fuel_type: Optional filter by fuel category.
        from_date: Optional inclusive start date filter on fill_date.
        to_date: Optional inclusive end date filter on fill_date.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``FuelLogResponse``.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    conditions = [
        CorporateFleetFuelLog.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetFuelLog.account_id == account_id,
    ]
    if fuel_type is not None:
        conditions.append(CorporateFleetFuelLog.fuel_type == fuel_type)
    if from_date is not None:
        conditions.append(CorporateFleetFuelLog.fill_date >= from_date)
    if to_date is not None:
        conditions.append(CorporateFleetFuelLog.fill_date <= to_date)

    stmt = (
        select(CorporateFleetFuelLog)
        .where(and_(*conditions))
        .order_by(CorporateFleetFuelLog.fill_date.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_vehicle_fuel_summary
# ---------------------------------------------------------------------------


async def get_vehicle_fuel_summary(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> VehicleFuelSummary:
    """Return fuel cost and efficiency analytics for a single fleet vehicle.

    Computes:
    - log_count: total fill-up records.
    - total_cost_usd: sum of all total_cost_usd values.
    - total_gallons: sum of all gallons_added values.
    - total_kwh: sum of all kwh_added values.
    - min/max odometer readings (when available).
    - total_miles_tracked: max_odometer - min_odometer (when both are available).
    - avg_mpg: total_miles_tracked / total_gallons (when both are available).
    - cost_per_mile_usd: total_cost / total_miles_tracked (when available).
    - first_fill_date / last_fill_date.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``VehicleFuelSummary``.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    stmt = select(CorporateFleetFuelLog).where(
        CorporateFleetFuelLog.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetFuelLog.account_id == account_id,
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())

    total_cost = sum(float(r.total_cost_usd) for r in logs if r.total_cost_usd is not None)
    total_gallons = sum(float(r.gallons_added) for r in logs if r.gallons_added is not None)
    total_kwh = sum(float(r.kwh_added) for r in logs if r.kwh_added is not None)

    odometer_readings = [r.odometer_miles for r in logs if r.odometer_miles is not None]
    min_odo = min(odometer_readings) if odometer_readings else None
    max_odo = max(odometer_readings) if odometer_readings else None
    total_miles = (max_odo - min_odo) if (min_odo is not None and max_odo is not None) else None

    avg_mpg = None
    if total_miles and total_gallons > 0:
        avg_mpg = round(total_miles / total_gallons, 2)

    cost_per_mile = None
    if total_miles and total_cost > 0:
        cost_per_mile = round(total_cost / total_miles, 4)

    fill_dates = [r.fill_date for r in logs]
    first_fill = min(fill_dates) if fill_dates else None
    last_fill = max(fill_dates) if fill_dates else None

    return VehicleFuelSummary(
        fleet_vehicle_id=fleet_vehicle_id,
        log_count=len(logs),
        total_cost_usd=round(total_cost, 2),
        total_gallons=round(total_gallons, 3),
        total_kwh=round(total_kwh, 3),
        min_odometer_miles=min_odo,
        max_odometer_miles=max_odo,
        total_miles_tracked=total_miles,
        avg_mpg=avg_mpg,
        cost_per_mile_usd=cost_per_mile,
        first_fill_date=first_fill,
        last_fill_date=last_fill,
    )


# ---------------------------------------------------------------------------
# list_account_fuel_logs
# ---------------------------------------------------------------------------


async def list_account_fuel_logs(
    db: AsyncSession,
    account_id: int,
    *,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
    fuel_type: Optional[FleetFuelType] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[FuelLogResponse]:
    """Return all fuel logs for a corporate account, with optional filters.

    Results are ordered by fill_date descending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: Optional filter to a specific vehicle.
        fuel_type: Optional filter by fuel category.
        from_date: Optional inclusive start date filter on fill_date.
        to_date: Optional inclusive end date filter on fill_date.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``FuelLogResponse``.
    """
    conditions = [CorporateFleetFuelLog.account_id == account_id]
    if fleet_vehicle_id is not None:
        conditions.append(CorporateFleetFuelLog.fleet_vehicle_id == fleet_vehicle_id)
    if fuel_type is not None:
        conditions.append(CorporateFleetFuelLog.fuel_type == fuel_type)
    if from_date is not None:
        conditions.append(CorporateFleetFuelLog.fill_date >= from_date)
    if to_date is not None:
        conditions.append(CorporateFleetFuelLog.fill_date <= to_date)

    stmt = (
        select(CorporateFleetFuelLog)
        .where(and_(*conditions))
        .order_by(CorporateFleetFuelLog.fill_date.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_fleet_fuel_summary
# ---------------------------------------------------------------------------


async def get_fleet_fuel_summary(
    db: AsyncSession,
    account_id: int,
) -> FleetFuelSummary:
    """Return fleet-wide fuel analytics for a corporate account.

    Computes:
    - total_logs: count of all fuel logs.
    - total_cost_usd: sum of all total_cost_usd.
    - total_gallons: sum of all gallons_added.
    - total_kwh: sum of all kwh_added.
    - by_fuel_type: per-type breakdown of count/cost/gallons/kwh.
    - vehicle_count: distinct vehicles with at least one log.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``FleetFuelSummary``.
    """
    stmt = select(CorporateFleetFuelLog).where(
        CorporateFleetFuelLog.account_id == account_id
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())

    total_cost = sum(float(r.total_cost_usd) for r in logs if r.total_cost_usd is not None)
    total_gallons = sum(float(r.gallons_added) for r in logs if r.gallons_added is not None)
    total_kwh = sum(float(r.kwh_added) for r in logs if r.kwh_added is not None)

    vehicle_ids = {r.fleet_vehicle_id for r in logs}

    # Per-type breakdown.
    type_buckets: dict[str, dict] = {}
    for ft in FleetFuelType:
        type_buckets[ft.value] = {"log_count": 0, "total_cost_usd": 0.0, "total_gallons": 0.0, "total_kwh": 0.0}

    for r in logs:
        key = r.fuel_type.value if hasattr(r.fuel_type, "value") else str(r.fuel_type)
        if key not in type_buckets:
            type_buckets[key] = {"log_count": 0, "total_cost_usd": 0.0, "total_gallons": 0.0, "total_kwh": 0.0}
        bucket = type_buckets[key]
        bucket["log_count"] += 1
        if r.total_cost_usd is not None:
            bucket["total_cost_usd"] += float(r.total_cost_usd)
        if r.gallons_added is not None:
            bucket["total_gallons"] += float(r.gallons_added)
        if r.kwh_added is not None:
            bucket["total_kwh"] += float(r.kwh_added)

    by_fuel_type = [
        FuelTypeBreakdown(
            fuel_type=ft,
            log_count=data["log_count"],
            total_cost_usd=round(data["total_cost_usd"], 2),
            total_gallons=round(data["total_gallons"], 3),
            total_kwh=round(data["total_kwh"], 3),
        )
        for ft, data in type_buckets.items()
    ]

    return FleetFuelSummary(
        total_logs=len(logs),
        total_cost_usd=round(total_cost, 2),
        total_gallons=round(total_gallons, 3),
        total_kwh=round(total_kwh, 3),
        by_fuel_type=by_fuel_type,
        vehicle_count=len(vehicle_ids),
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[FuelLogResponse]:
    """Return fuel logs across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``FuelLogResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateFleetFuelLog.account_id == account_id)

    base = select(CorporateFleetFuelLog)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetFuelLog.account_id,
            CorporateFleetFuelLog.fill_date.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
