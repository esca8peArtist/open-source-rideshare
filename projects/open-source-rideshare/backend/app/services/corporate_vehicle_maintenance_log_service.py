"""Service layer for Corporate Vehicle Maintenance Log.

Fleet managers track service history for company vehicles — oil changes,
inspections, tire rotations, brake services, and other maintenance events.
Records may be scheduled (future) or historical (completed).

Public functions
----------------
create_maintenance_record   — create a new maintenance record (404 vehicle; 409 inactive).
get_maintenance_record      — fetch one record (404 if missing or wrong account).
list_maintenance_records    — filtered, paginated list for an account.
list_vehicle_maintenance    — all records for a specific fleet vehicle.
update_maintenance_record   — partial update (404).
complete_maintenance_record — mark as completed (409 if already complete).
delete_maintenance_record   — delete a record (409 if completed).
get_upcoming_maintenance    — records with next_due_date within N days.
get_maintenance_summary     — aggregate stats for an account.
list_all_platform           — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_vehicle_maintenance_log import (
    CorporateVehicleMaintenanceLog,
    MaintenanceType,
)
from app.schemas.corporate_vehicle_maintenance_log import (
    MaintenanceLogComplete,
    MaintenanceLogCreate,
    MaintenanceLogResponse,
    MaintenanceSummaryResponse,
    MaintenanceUpcomingResponse,
    MaintenanceLogUpdate,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateVehicleMaintenanceLog) -> MaintenanceLogResponse:
    return MaintenanceLogResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

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
) -> CorporateVehicleMaintenanceLog:
    """Return a maintenance log verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the maintenance log.

    Returns:
        ``CorporateVehicleMaintenanceLog`` ORM instance.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    stmt = select(CorporateVehicleMaintenanceLog).where(
        CorporateVehicleMaintenanceLog.id == log_id,
        CorporateVehicleMaintenanceLog.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found.",
        )
    return row


# ---------------------------------------------------------------------------
# create_maintenance_record
# ---------------------------------------------------------------------------


async def create_maintenance_record(
    db: AsyncSession,
    account_id: int,
    data: MaintenanceLogCreate,
    created_by_id: Optional[int] = None,
) -> MaintenanceLogResponse:
    """Create a new maintenance record for a corporate fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Maintenance record creation payload.
        created_by_id: ID of the user creating the record.

    Returns:
        ``MaintenanceLogResponse`` for the new record.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
        HTTPException 409: Fleet vehicle is inactive.
    """
    vehicle = await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)

    if not vehicle.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet vehicle is not active.",
        )

    log = CorporateVehicleMaintenanceLog(
        id=uuid.uuid4(),
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        maintenance_type=data.maintenance_type,
        title=data.title,
        description=data.description,
        scheduled_date=data.scheduled_date,
        odometer_miles=data.odometer_miles,
        cost_usd=float(data.cost_usd) if data.cost_usd is not None else None,
        vendor_name=data.vendor_name,
        notes=data.notes,
        is_completed=False,
        next_due_date=data.next_due_date,
        next_due_odometer=data.next_due_odometer,
        created_by_id=created_by_id,
        completed_by_id=None,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _to_response(log)


# ---------------------------------------------------------------------------
# get_maintenance_record
# ---------------------------------------------------------------------------


async def get_maintenance_record(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
) -> MaintenanceLogResponse:
    """Return a single maintenance record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the maintenance record.

    Returns:
        ``MaintenanceLogResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    row = await _fetch_log(db, account_id, log_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_maintenance_records
# ---------------------------------------------------------------------------


async def list_maintenance_records(
    db: AsyncSession,
    account_id: int,
    *,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
    maintenance_type: Optional[MaintenanceType] = None,
    is_completed: Optional[bool] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[MaintenanceLogResponse]:
    """Return a filtered, paginated list of maintenance records for an account.

    Results are ordered by created_at descending (newest first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: Optional filter by vehicle UUID.
        maintenance_type: Optional filter by maintenance category.
        is_completed: Optional filter by completion status.
        from_date: Optional filter: scheduled_date >= from_date.
        to_date: Optional filter: scheduled_date <= to_date.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``MaintenanceLogResponse``.
    """
    conditions = [CorporateVehicleMaintenanceLog.account_id == account_id]
    if fleet_vehicle_id is not None:
        conditions.append(
            CorporateVehicleMaintenanceLog.fleet_vehicle_id == fleet_vehicle_id
        )
    if maintenance_type is not None:
        conditions.append(
            CorporateVehicleMaintenanceLog.maintenance_type == maintenance_type
        )
    if is_completed is not None:
        conditions.append(
            CorporateVehicleMaintenanceLog.is_completed == is_completed
        )
    if from_date is not None:
        conditions.append(
            CorporateVehicleMaintenanceLog.scheduled_date >= from_date
        )
    if to_date is not None:
        conditions.append(
            CorporateVehicleMaintenanceLog.scheduled_date <= to_date
        )

    stmt = (
        select(CorporateVehicleMaintenanceLog)
        .where(and_(*conditions))
        .order_by(CorporateVehicleMaintenanceLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_vehicle_maintenance
# ---------------------------------------------------------------------------


async def list_vehicle_maintenance(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[MaintenanceLogResponse]:
    """Return all maintenance records for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the vehicle.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``MaintenanceLogResponse``, newest first.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    stmt = (
        select(CorporateVehicleMaintenanceLog)
        .where(
            CorporateVehicleMaintenanceLog.account_id == account_id,
            CorporateVehicleMaintenanceLog.fleet_vehicle_id == fleet_vehicle_id,
        )
        .order_by(CorporateVehicleMaintenanceLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_maintenance_record
# ---------------------------------------------------------------------------


async def update_maintenance_record(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
    data: MaintenanceLogUpdate,
) -> MaintenanceLogResponse:
    """Partially update a maintenance record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the maintenance record.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``MaintenanceLogResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    row = await _fetch_log(db, account_id, log_id)

    update_data = data.model_dump(exclude_none=True)
    if "cost_usd" in update_data and update_data["cost_usd"] is not None:
        update_data["cost_usd"] = float(update_data["cost_usd"])

    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# complete_maintenance_record
# ---------------------------------------------------------------------------


async def complete_maintenance_record(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
    data: MaintenanceLogComplete,
    completed_by_id: Optional[int] = None,
) -> MaintenanceLogResponse:
    """Mark a maintenance record as completed.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the maintenance record.
        data: Completion payload (timestamps, cost, vendor, next-due fields).
        completed_by_id: ID of the user performing the completion action.

    Returns:
        Updated ``MaintenanceLogResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
        HTTPException 409: Record is already completed.
    """
    row = await _fetch_log(db, account_id, log_id)

    if row.is_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maintenance record is already marked as completed.",
        )

    row.is_completed = True
    row.completed_at = data.completed_at or datetime.now(tz=timezone.utc)
    row.completed_by_id = completed_by_id

    if data.odometer_miles is not None:
        row.odometer_miles = data.odometer_miles
    if data.cost_usd is not None:
        row.cost_usd = float(data.cost_usd)
    if data.vendor_name is not None:
        row.vendor_name = data.vendor_name
    if data.notes is not None:
        row.notes = data.notes
    if data.next_due_date is not None:
        row.next_due_date = data.next_due_date
    if data.next_due_odometer is not None:
        row.next_due_odometer = data.next_due_odometer

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# delete_maintenance_record
# ---------------------------------------------------------------------------


async def delete_maintenance_record(
    db: AsyncSession,
    account_id: int,
    log_id: uuid.UUID,
) -> None:
    """Delete a maintenance record.

    Only non-completed records may be deleted.  Use update to correct completed
    records instead.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        log_id: UUID of the maintenance record.

    Raises:
        HTTPException 404: Record not found or wrong account.
        HTTPException 409: Completed records cannot be deleted.
    """
    row = await _fetch_log(db, account_id, log_id)

    if row.is_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completed maintenance records cannot be deleted.",
        )

    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# get_upcoming_maintenance
# ---------------------------------------------------------------------------


async def get_upcoming_maintenance(
    db: AsyncSession,
    account_id: int,
    *,
    days_ahead: int = 30,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
) -> list[MaintenanceUpcomingResponse]:
    """Return records where next_due_date falls within the next N days.

    Only non-completed records with a next_due_date set are included.
    Results are ordered by next_due_date ascending (most urgent first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        days_ahead: Look-ahead window in days (default 30).
        fleet_vehicle_id: Optional filter to a specific vehicle.

    Returns:
        List of ``MaintenanceUpcomingResponse``.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff = now + timedelta(days=days_ahead)

    conditions = [
        CorporateVehicleMaintenanceLog.account_id == account_id,
        CorporateVehicleMaintenanceLog.is_completed == False,  # noqa: E712
        CorporateVehicleMaintenanceLog.next_due_date.isnot(None),
        CorporateVehicleMaintenanceLog.next_due_date <= cutoff,
    ]
    if fleet_vehicle_id is not None:
        conditions.append(
            CorporateVehicleMaintenanceLog.fleet_vehicle_id == fleet_vehicle_id
        )

    stmt = (
        select(CorporateVehicleMaintenanceLog)
        .where(and_(*conditions))
        .order_by(CorporateVehicleMaintenanceLog.next_due_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    alerts = []
    for row in rows:
        due = row.next_due_date
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        days_until = max(0, (due.date() - now.date()).days)
        alerts.append(
            MaintenanceUpcomingResponse(
                log_id=row.id,
                fleet_vehicle_id=row.fleet_vehicle_id,
                maintenance_type=row.maintenance_type.value
                if hasattr(row.maintenance_type, "value")
                else str(row.maintenance_type),
                title=row.title,
                next_due_date=due,
                days_until_due=days_until,
                next_due_odometer=row.next_due_odometer,
            )
        )
    return alerts


# ---------------------------------------------------------------------------
# get_maintenance_summary
# ---------------------------------------------------------------------------


async def get_maintenance_summary(
    db: AsyncSession,
    account_id: int,
) -> MaintenanceSummaryResponse:
    """Return aggregate maintenance statistics for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``MaintenanceSummaryResponse`` with counts and cost totals.
    """
    now = datetime.now(tz=timezone.utc)

    stmt = select(CorporateVehicleMaintenanceLog).where(
        CorporateVehicleMaintenanceLog.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    total = len(rows)
    completed = sum(1 for r in rows if r.is_completed)
    pending = total - completed

    overdue = sum(
        1
        for r in rows
        if not r.is_completed
        and r.next_due_date is not None
        and r.next_due_date <= now
    )

    cutoff_30 = now + timedelta(days=30)
    due_within_30 = sum(
        1
        for r in rows
        if not r.is_completed
        and r.next_due_date is not None
        and now < r.next_due_date <= cutoff_30
    )

    total_cost = sum(
        float(r.cost_usd) for r in rows if r.cost_usd is not None
    )

    by_type: dict[str, int] = {t.value: 0 for t in MaintenanceType}
    for row in rows:
        key = (
            row.maintenance_type.value
            if hasattr(row.maintenance_type, "value")
            else str(row.maintenance_type)
        )
        by_type[key] = by_type.get(key, 0) + 1

    return MaintenanceSummaryResponse(
        total_records=total,
        completed=completed,
        pending=pending,
        overdue=overdue,
        due_within_30_days=due_within_30,
        total_cost_usd=round(total_cost, 2),
        by_type=by_type,
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
) -> list[MaintenanceLogResponse]:
    """Return maintenance records across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``MaintenanceLogResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateVehicleMaintenanceLog.account_id == account_id)

    base = select(CorporateVehicleMaintenanceLog)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateVehicleMaintenanceLog.account_id,
            CorporateVehicleMaintenanceLog.created_at.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
