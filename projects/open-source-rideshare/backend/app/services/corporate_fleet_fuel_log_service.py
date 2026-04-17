"""Service layer for Corporate Fleet Fuel Log tracking.

Fleet managers and drivers log fuel fill-ups and EV charging events for
company vehicles.  Over time the logs enable fuel-cost and mileage
analytics (MPG / cost-per-mile).

Public surface
--------------
create_fuel_log(db, account_id, vehicle_id, data, actor)
update_fuel_log(db, log_id, data, actor)
delete_fuel_log(db, log_id, actor)
list_fuel_logs_for_vehicle(db, account_id, vehicle_id, actor, skip, limit)
list_fuel_logs_for_account(db, account_id, actor, skip, limit)
get_vehicle_fuel_summary(db, account_id, vehicle_id, actor)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_fleet_fuel_log import (
    CorporateFleetFuelLog,
    FleetFuelType,
)
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.schemas.corporate_fleet_fuel_log import (
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    VehicleFuelSummaryAnalytics,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active member of the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        user_id: ID of the requesting user.

    Returns:
        ``BusinessAccountMember`` ORM instance.

    Raises:
        HTTPException 403: User is not an active member.
    """
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
    """Raise HTTP 403 when the user is not an active admin of the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        user_id: ID of the requesting user.

    Returns:
        ``BusinessAccountMember`` ORM instance.

    Raises:
        HTTPException 403: User is not an active admin.
    """
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


async def _fetch_vehicle(
    db: AsyncSession, account_id: int, vehicle_id: uuid.UUID
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    result = await db.execute(
        select(CorporateFleetVehicle).where(
            CorporateFleetVehicle.id == vehicle_id,
            CorporateFleetVehicle.account_id == account_id,
        )
    )
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found for this account.",
        )
    return vehicle


async def _fetch_log(
    db: AsyncSession, log_id: uuid.UUID
) -> CorporateFleetFuelLog:
    """Return a fuel log record by ID.

    Args:
        db: Async SQLAlchemy session.
        log_id: UUID of the fuel log.

    Returns:
        ``CorporateFleetFuelLog`` ORM instance.

    Raises:
        HTTPException 404: Fuel log not found.
    """
    result = await db.execute(
        select(CorporateFleetFuelLog).where(CorporateFleetFuelLog.id == log_id)
    )
    log = result.scalar_one_or_none()
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fuel log not found.",
        )
    return log


def _to_response(row: CorporateFleetFuelLog) -> FuelLogResponse:
    return FuelLogResponse.model_validate(row)


# ---------------------------------------------------------------------------
# create_fuel_log
# ---------------------------------------------------------------------------


async def create_fuel_log(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    data: FuelLogCreate,
    actor_id: int,
) -> FuelLogResponse:
    """Create a fuel log entry for a fleet vehicle.

    The actor must be an active member or admin of the corporate account.
    The vehicle must belong to the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.
        data: Fuel log creation payload.
        actor_id: ID of the authenticated user creating the entry.

    Returns:
        ``FuelLogResponse`` for the new log.

    Raises:
        HTTPException 403: Actor is not a member of the account.
        HTTPException 404: Vehicle not found for this account.
    """
    await _require_account_member(db, account_id, actor_id)
    await _fetch_vehicle(db, account_id, vehicle_id)

    log = CorporateFleetFuelLog(
        id=uuid.uuid4(),
        fleet_vehicle_id=vehicle_id,
        account_id=account_id,
        fuel_type=data.fuel_type,
        fill_date=data.fill_date,
        odometer_miles=data.odometer_miles,
        gallons_added=float(data.gallons_added) if data.gallons_added is not None else None,
        kwh_added=float(data.kwh_added) if data.kwh_added is not None else None,
        cost_per_unit_usd=float(data.cost_per_unit_usd) if data.cost_per_unit_usd is not None else None,
        total_cost_usd=float(data.total_cost_usd) if data.total_cost_usd is not None else None,
        station_name=data.station_name,
        notes=data.notes,
        logged_by_id=actor_id,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _to_response(log)


# ---------------------------------------------------------------------------
# update_fuel_log
# ---------------------------------------------------------------------------


async def update_fuel_log(
    db: AsyncSession,
    log_id: uuid.UUID,
    data: FuelLogUpdate,
    actor_id: int,
) -> FuelLogResponse:
    """Update a fuel log entry.

    The actor must either own the log (logged_by_id == actor_id) or be an
    admin of the account the log belongs to.

    Args:
        db: Async SQLAlchemy session.
        log_id: UUID of the fuel log to update.
        data: Partial update payload.
        actor_id: ID of the authenticated user.

    Returns:
        Updated ``FuelLogResponse``.

    Raises:
        HTTPException 403: Actor does not own the log and is not an account admin.
        HTTPException 404: Fuel log not found.
    """
    log = await _fetch_log(db, log_id)

    # Check: actor owns the log OR is an admin of the account
    is_owner = log.logged_by_id == actor_id
    if not is_owner:
        await _require_account_admin(db, log.account_id, actor_id)

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field in ("gallons_added", "kwh_added", "cost_per_unit_usd", "total_cost_usd"):
            value = float(value) if value is not None else None
        setattr(log, field, value)

    await db.commit()
    await db.refresh(log)
    return _to_response(log)


# ---------------------------------------------------------------------------
# delete_fuel_log
# ---------------------------------------------------------------------------


async def delete_fuel_log(
    db: AsyncSession,
    log_id: uuid.UUID,
    actor_id: int,
) -> None:
    """Delete a fuel log entry.

    The actor must either own the log or be an admin of the account.

    Args:
        db: Async SQLAlchemy session.
        log_id: UUID of the fuel log to delete.
        actor_id: ID of the authenticated user.

    Raises:
        HTTPException 403: Actor does not own the log and is not an account admin.
        HTTPException 404: Fuel log not found.
    """
    log = await _fetch_log(db, log_id)

    is_owner = log.logged_by_id == actor_id
    if not is_owner:
        await _require_account_admin(db, log.account_id, actor_id)

    await db.delete(log)
    await db.commit()


# ---------------------------------------------------------------------------
# list_fuel_logs_for_vehicle
# ---------------------------------------------------------------------------


async def list_fuel_logs_for_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    actor_id: int,
    skip: int = 0,
    limit: int = 50,
) -> List[FuelLogResponse]:
    """Return fuel logs for a specific fleet vehicle.

    The actor must be an active member of the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.
        actor_id: ID of the authenticated user.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``FuelLogResponse``.

    Raises:
        HTTPException 403: Actor is not a member of the account.
        HTTPException 404: Vehicle not found for this account.
    """
    await _require_account_member(db, account_id, actor_id)
    await _fetch_vehicle(db, account_id, vehicle_id)

    stmt = (
        select(CorporateFleetFuelLog)
        .where(
            and_(
                CorporateFleetFuelLog.account_id == account_id,
                CorporateFleetFuelLog.fleet_vehicle_id == vehicle_id,
            )
        )
        .order_by(CorporateFleetFuelLog.fill_date.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_fuel_logs_for_account
# ---------------------------------------------------------------------------


async def list_fuel_logs_for_account(
    db: AsyncSession,
    account_id: int,
    actor_id: int,
    skip: int = 0,
    limit: int = 100,
) -> List[FuelLogResponse]:
    """Return fleet-wide fuel logs for a corporate account (admin only).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        actor_id: ID of the authenticated user (must be admin).
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``FuelLogResponse``.

    Raises:
        HTTPException 403: Actor is not an admin of the account.
    """
    await _require_account_admin(db, account_id, actor_id)

    stmt = (
        select(CorporateFleetFuelLog)
        .where(CorporateFleetFuelLog.account_id == account_id)
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

# Fuel types that use gallons (ICE / hybrid)
_GALLON_TYPES = {FleetFuelType.gasoline, FleetFuelType.diesel, FleetFuelType.hybrid}
# Fuel type that uses kWh
_KWH_TYPES = {FleetFuelType.electric}


async def get_vehicle_fuel_summary(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    actor_id: int,
) -> VehicleFuelSummaryAnalytics:
    """Return per-vehicle fuel analytics for a fleet vehicle.

    The actor must be an active member of the account.

    Analytics:
        total_fill_ups: total count of log entries.
        total_gallons: sum of gallons_added (ICE / hybrid logs).
        total_kwh: sum of kwh_added (EV logs).
        total_cost_usd: sum of total_cost_usd across all logs.
        avg_cost_per_gallon_usd: avg cost_per_unit_usd for gasoline/diesel/hybrid logs.
        avg_cost_per_kwh_usd: avg cost_per_unit_usd for electric logs.
        last_fill_date: date of the most recent fill-up.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.
        actor_id: ID of the authenticated user.

    Returns:
        ``VehicleFuelSummaryAnalytics``.

    Raises:
        HTTPException 403: Actor is not a member of the account.
        HTTPException 404: Vehicle not found for this account.
    """
    await _require_account_member(db, account_id, actor_id)
    await _fetch_vehicle(db, account_id, vehicle_id)

    base_where = and_(
        CorporateFleetFuelLog.account_id == account_id,
        CorporateFleetFuelLog.fleet_vehicle_id == vehicle_id,
    )

    # Total fill-ups, total cost, last fill date
    agg_result = await db.execute(
        select(
            func.count(CorporateFleetFuelLog.id).label("total_fill_ups"),
            func.coalesce(func.sum(CorporateFleetFuelLog.total_cost_usd), 0).label("total_cost_usd"),
            func.max(CorporateFleetFuelLog.fill_date).label("last_fill_date"),
        ).where(base_where)
    )
    agg_row = agg_result.one()

    # Gallons sum (ICE / hybrid)
    gallons_result = await db.execute(
        select(
            func.coalesce(func.sum(CorporateFleetFuelLog.gallons_added), 0).label("total_gallons")
        ).where(
            and_(
                base_where,
                CorporateFleetFuelLog.fuel_type.in_([t.value for t in _GALLON_TYPES]),
            )
        )
    )
    total_gallons = Decimal(str(gallons_result.scalar_one() or 0))

    # kWh sum (EV)
    kwh_result = await db.execute(
        select(
            func.coalesce(func.sum(CorporateFleetFuelLog.kwh_added), 0).label("total_kwh")
        ).where(
            and_(
                base_where,
                CorporateFleetFuelLog.fuel_type.in_([t.value for t in _KWH_TYPES]),
            )
        )
    )
    total_kwh = Decimal(str(kwh_result.scalar_one() or 0))

    # Avg cost per gallon (gasoline / diesel / hybrid)
    avg_gallon_result = await db.execute(
        select(
            func.avg(CorporateFleetFuelLog.cost_per_unit_usd).label("avg_cost_per_gallon")
        ).where(
            and_(
                base_where,
                CorporateFleetFuelLog.fuel_type.in_([t.value for t in _GALLON_TYPES]),
                CorporateFleetFuelLog.cost_per_unit_usd.is_not(None),
            )
        )
    )
    avg_gallon_raw = avg_gallon_result.scalar_one()
    avg_cost_per_gallon = Decimal(str(avg_gallon_raw)) if avg_gallon_raw is not None else None

    # Avg cost per kWh (electric)
    avg_kwh_result = await db.execute(
        select(
            func.avg(CorporateFleetFuelLog.cost_per_unit_usd).label("avg_cost_per_kwh")
        ).where(
            and_(
                base_where,
                CorporateFleetFuelLog.fuel_type.in_([t.value for t in _KWH_TYPES]),
                CorporateFleetFuelLog.cost_per_unit_usd.is_not(None),
            )
        )
    )
    avg_kwh_raw = avg_kwh_result.scalar_one()
    avg_cost_per_kwh = Decimal(str(avg_kwh_raw)) if avg_kwh_raw is not None else None

    return VehicleFuelSummaryAnalytics(
        fleet_vehicle_id=vehicle_id,
        total_fill_ups=agg_row.total_fill_ups or 0,
        total_gallons=total_gallons,
        total_kwh=total_kwh,
        total_cost_usd=Decimal(str(agg_row.total_cost_usd or 0)),
        avg_cost_per_gallon_usd=avg_cost_per_gallon,
        avg_cost_per_kwh_usd=avg_cost_per_kwh,
        last_fill_date=agg_row.last_fill_date,
    )
