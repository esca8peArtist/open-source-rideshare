"""Service layer for Corporate Fleet Maintenance Scheduling.

Fleet managers schedule preventive maintenance and log completed service
records for company vehicles.

Public functions
----------------
schedule_maintenance            — create a new scheduled maintenance record (404 vehicle).
get_maintenance_record          — fetch one record (404 if missing or wrong account).
update_maintenance_record       — partial update (404).
complete_maintenance            — mark a record completed with date, cost, odometer.
cancel_maintenance              — cancel a scheduled record (409 if completed/cancelled).
delete_maintenance_record       — delete a record (404).
list_vehicle_maintenance        — filtered list for a specific vehicle.
list_account_maintenance        — filtered, paginated fleet-wide list.
get_overdue_maintenance         — records past their scheduled/next_service date, marks overdue.
get_vehicle_maintenance_summary — aggregate stats for a vehicle.
get_account_maintenance_summary — aggregate stats for an account.
list_all_platform               — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_fleet_maintenance import (
    CorporateFleetMaintenanceRecord,
    FleetMaintenanceStatus,
    FleetMaintenanceType,
)
from app.schemas.corporate_fleet_maintenance import (
    AccountMaintenanceSummaryResponse,
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
    MaintenanceTypeBreakdown,
    VehicleMaintenanceSummaryResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateFleetMaintenanceRecord) -> MaintenanceRecordResponse:
    return MaintenanceRecordResponse.model_validate(row)


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


async def _fetch_record(
    db: AsyncSession,
    account_id: int,
    record_id: uuid.UUID,
) -> CorporateFleetMaintenanceRecord:
    """Return a maintenance record verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        record_id: UUID of the maintenance record.

    Returns:
        ``CorporateFleetMaintenanceRecord`` ORM instance.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    stmt = select(CorporateFleetMaintenanceRecord).where(
        CorporateFleetMaintenanceRecord.id == record_id,
        CorporateFleetMaintenanceRecord.account_id == account_id,
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
# schedule_maintenance
# ---------------------------------------------------------------------------


async def schedule_maintenance(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    data: MaintenanceRecordCreate,
    created_by_id: Optional[int] = None,
) -> MaintenanceRecordResponse:
    """Create a new scheduled maintenance record for a corporate fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.
        data: Maintenance creation payload.
        created_by_id: ID of the user creating the record.

    Returns:
        ``MaintenanceRecordResponse`` for the new record.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    record = CorporateFleetMaintenanceRecord(
        id=uuid.uuid4(),
        account_id=account_id,
        fleet_vehicle_id=vehicle_id,
        maintenance_type=data.maintenance_type,
        status=FleetMaintenanceStatus.scheduled,
        scheduled_date=data.scheduled_date,
        description=data.description,
        vendor_name=data.vendor_name,
        cost_usd=float(data.cost_usd) if data.cost_usd is not None else None,
        odometer_at_service=data.odometer_at_service,
        next_service_odometer=data.next_service_odometer,
        next_service_date=data.next_service_date,
        created_by_id=created_by_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _to_response(record)


# ---------------------------------------------------------------------------
# get_maintenance_record
# ---------------------------------------------------------------------------


async def get_maintenance_record(
    db: AsyncSession,
    account_id: int,
    record_id: uuid.UUID,
) -> MaintenanceRecordResponse:
    """Return a single maintenance record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        record_id: UUID of the maintenance record.

    Returns:
        ``MaintenanceRecordResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    row = await _fetch_record(db, account_id, record_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# update_maintenance_record
# ---------------------------------------------------------------------------


async def update_maintenance_record(
    db: AsyncSession,
    account_id: int,
    record_id: uuid.UUID,
    data: MaintenanceRecordUpdate,
) -> MaintenanceRecordResponse:
    """Partially update a maintenance record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        record_id: UUID of the maintenance record.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``MaintenanceRecordResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    row = await _fetch_record(db, account_id, record_id)

    update_data = data.model_dump(exclude_none=True)

    for field, value in update_data.items():
        if field == "cost_usd":
            value = float(value) if value is not None else None
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# complete_maintenance
# ---------------------------------------------------------------------------


async def complete_maintenance(
    db: AsyncSession,
    account_id: int,
    record_id: uuid.UUID,
    completed_date: Optional[date] = None,
    cost_usd: Optional[float] = None,
    odometer: Optional[int] = None,
) -> MaintenanceRecordResponse:
    """Mark a maintenance record as completed.

    Sets status to completed, and optionally records the completed_date,
    cost_usd, and odometer_at_service.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        record_id: UUID of the maintenance record.
        completed_date: Date the service was completed.
        cost_usd: Total service cost in USD.
        odometer: Odometer reading at time of service.

    Returns:
        Updated ``MaintenanceRecordResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    row = await _fetch_record(db, account_id, record_id)

    row.status = FleetMaintenanceStatus.completed
    if completed_date is not None:
        row.completed_date = completed_date
    if cost_usd is not None:
        row.cost_usd = float(cost_usd)
    if odometer is not None:
        row.odometer_at_service = odometer

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# cancel_maintenance
# ---------------------------------------------------------------------------


async def cancel_maintenance(
    db: AsyncSession,
    account_id: int,
    record_id: uuid.UUID,
) -> MaintenanceRecordResponse:
    """Cancel a scheduled maintenance record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        record_id: UUID of the maintenance record.

    Returns:
        Updated ``MaintenanceRecordResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
        HTTPException 409: Record is already completed or cancelled.
    """
    row = await _fetch_record(db, account_id, record_id)

    if row.status in (
        FleetMaintenanceStatus.completed,
        FleetMaintenanceStatus.cancelled,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Maintenance record is already {row.status.value}.",
        )

    row.status = FleetMaintenanceStatus.cancelled
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# delete_maintenance_record
# ---------------------------------------------------------------------------


async def delete_maintenance_record(
    db: AsyncSession,
    account_id: int,
    record_id: uuid.UUID,
) -> None:
    """Delete a maintenance record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        record_id: UUID of the maintenance record.

    Raises:
        HTTPException 404: Record not found or wrong account.
    """
    row = await _fetch_record(db, account_id, record_id)
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# list_vehicle_maintenance
# ---------------------------------------------------------------------------


async def list_vehicle_maintenance(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    *,
    status: Optional[FleetMaintenanceStatus] = None,
    maintenance_type: Optional[FleetMaintenanceType] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[MaintenanceRecordResponse]:
    """Return maintenance records for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.
        status: Optional filter by status.
        maintenance_type: Optional filter by maintenance type.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``MaintenanceRecordResponse``.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    conditions = [
        CorporateFleetMaintenanceRecord.account_id == account_id,
        CorporateFleetMaintenanceRecord.fleet_vehicle_id == vehicle_id,
    ]
    if status is not None:
        conditions.append(CorporateFleetMaintenanceRecord.status == status)
    if maintenance_type is not None:
        conditions.append(
            CorporateFleetMaintenanceRecord.maintenance_type == maintenance_type
        )

    stmt = (
        select(CorporateFleetMaintenanceRecord)
        .where(and_(*conditions))
        .order_by(CorporateFleetMaintenanceRecord.scheduled_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_account_maintenance
# ---------------------------------------------------------------------------


async def list_account_maintenance(
    db: AsyncSession,
    account_id: int,
    *,
    vehicle_id: Optional[uuid.UUID] = None,
    status: Optional[FleetMaintenanceStatus] = None,
    maintenance_type: Optional[FleetMaintenanceType] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[MaintenanceRecordResponse]:
    """Return a filtered, paginated list of maintenance records for an account.

    Results are ordered by scheduled_date ascending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: Optional filter to a specific vehicle.
        status: Optional filter by status.
        maintenance_type: Optional filter by maintenance type.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``MaintenanceRecordResponse``.
    """
    conditions = [CorporateFleetMaintenanceRecord.account_id == account_id]
    if vehicle_id is not None:
        conditions.append(
            CorporateFleetMaintenanceRecord.fleet_vehicle_id == vehicle_id
        )
    if status is not None:
        conditions.append(CorporateFleetMaintenanceRecord.status == status)
    if maintenance_type is not None:
        conditions.append(
            CorporateFleetMaintenanceRecord.maintenance_type == maintenance_type
        )

    stmt = (
        select(CorporateFleetMaintenanceRecord)
        .where(and_(*conditions))
        .order_by(CorporateFleetMaintenanceRecord.scheduled_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_overdue_maintenance
# ---------------------------------------------------------------------------


async def get_overdue_maintenance(
    db: AsyncSession,
    account_id: int,
) -> List[MaintenanceRecordResponse]:
    """Return records that are overdue and mark them as overdue in the DB.

    A scheduled record is overdue when:
      - its status is ``scheduled`` or ``in_progress``, AND
      - its scheduled_date is in the past OR its next_service_date is in the past.

    Overdue records are updated to status=overdue and committed before being
    returned.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        List of ``MaintenanceRecordResponse`` for overdue records.
    """
    today = date.today()

    stmt = select(CorporateFleetMaintenanceRecord).where(
        CorporateFleetMaintenanceRecord.account_id == account_id,
        CorporateFleetMaintenanceRecord.status.in_(
            [FleetMaintenanceStatus.scheduled, FleetMaintenanceStatus.in_progress]
        ),
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    overdue_rows = []
    for row in rows:
        scheduled_past = row.scheduled_date is not None and row.scheduled_date < today
        next_service_past = (
            row.next_service_date is not None and row.next_service_date < today
        )
        if scheduled_past or next_service_past:
            row.status = FleetMaintenanceStatus.overdue
            overdue_rows.append(row)

    if overdue_rows:
        await db.commit()
        for row in overdue_rows:
            await db.refresh(row)

    return [_to_response(r) for r in overdue_rows]


# ---------------------------------------------------------------------------
# get_vehicle_maintenance_summary
# ---------------------------------------------------------------------------


async def get_vehicle_maintenance_summary(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> VehicleMaintenanceSummaryResponse:
    """Return aggregate maintenance statistics for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``VehicleMaintenanceSummaryResponse``.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    stmt = select(CorporateFleetMaintenanceRecord).where(
        CorporateFleetMaintenanceRecord.account_id == account_id,
        CorporateFleetMaintenanceRecord.fleet_vehicle_id == vehicle_id,
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    total_cost = sum(
        float(r.cost_usd) for r in rows if r.cost_usd is not None
    )

    completed_dates = [
        r.completed_date for r in rows if r.completed_date is not None
    ]
    last_service = max(completed_dates) if completed_dates else None

    today = date.today()
    upcoming_dates = [
        r.scheduled_date
        for r in rows
        if r.scheduled_date is not None
        and r.scheduled_date >= today
        and r.status == FleetMaintenanceStatus.scheduled
    ]
    next_scheduled = min(upcoming_dates) if upcoming_dates else None

    overdue_count = sum(
        1 for r in rows if r.status == FleetMaintenanceStatus.overdue
    )

    # Per-type breakdown
    type_map: dict[FleetMaintenanceType, dict] = {}
    for row in rows:
        mt = row.maintenance_type
        if mt not in type_map:
            type_map[mt] = {"count": 0, "total_cost_usd": 0.0}
        type_map[mt]["count"] += 1
        if row.cost_usd is not None:
            type_map[mt]["total_cost_usd"] += float(row.cost_usd)

    per_type = [
        MaintenanceTypeBreakdown(
            maintenance_type=mt,
            count=v["count"],
            total_cost_usd=round(v["total_cost_usd"], 2),
        )
        for mt, v in type_map.items()
    ]

    return VehicleMaintenanceSummaryResponse(
        vehicle_id=vehicle_id,
        total_records=len(rows),
        total_cost_usd=round(total_cost, 2),
        last_service_date=last_service,
        next_scheduled_date=next_scheduled,
        overdue_count=overdue_count,
        per_type=per_type,
    )


# ---------------------------------------------------------------------------
# get_account_maintenance_summary
# ---------------------------------------------------------------------------


async def get_account_maintenance_summary(
    db: AsyncSession,
    account_id: int,
) -> AccountMaintenanceSummaryResponse:
    """Return account-wide aggregate maintenance statistics.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``AccountMaintenanceSummaryResponse``.
    """
    stmt = select(CorporateFleetMaintenanceRecord).where(
        CorporateFleetMaintenanceRecord.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    total_cost = sum(
        float(r.cost_usd) for r in rows if r.cost_usd is not None
    )

    overdue_rows = [r for r in rows if r.status == FleetMaintenanceStatus.overdue]
    overdue_count = len(overdue_rows)

    vehicles_with_overdue = list(
        {r.fleet_vehicle_id for r in overdue_rows}
    )

    return AccountMaintenanceSummaryResponse(
        account_id=account_id,
        total_records=len(rows),
        total_cost_usd=round(total_cost, 2),
        overdue_count=overdue_count,
        vehicles_with_overdue=vehicles_with_overdue,
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 200,
) -> List[MaintenanceRecordResponse]:
    """Return maintenance records across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 200).

    Returns:
        List of ``MaintenanceRecordResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(
            CorporateFleetMaintenanceRecord.account_id == account_id
        )

    base = select(CorporateFleetMaintenanceRecord)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetMaintenanceRecord.account_id,
            CorporateFleetMaintenanceRecord.scheduled_date.asc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
