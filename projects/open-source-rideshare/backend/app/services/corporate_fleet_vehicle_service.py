"""Service layer for Corporate Fleet Vehicle Management.

Enterprise corporate accounts can define a pool of company-owned or leased
vehicles and assign drivers to them.

Public functions
----------------
create_fleet_vehicle    — create a new vehicle in the fleet (409 on name duplicate).
get_fleet_vehicle       — fetch a single vehicle (404 if missing or wrong account).
list_fleet_vehicles     — filtered, paginated list of vehicles for an account.
update_fleet_vehicle    — partial update (409 on name collision).
deactivate_fleet_vehicle — set is_active=False (409 if already inactive).
reactivate_fleet_vehicle — set is_active=True (409 if already active).
delete_fleet_vehicle    — hard delete (409 if still active).
assign_driver           — assign a driver; deactivates any prior active assignment.
end_assignment          — deactivate the current active assignment (404 if none).
get_active_assignment   — return the current active assignment or None.
list_vehicle_assignments — full assignment history, newest-first.
get_fleet_summary       — aggregate fleet statistics for an account.
list_all_platform       — platform-admin cross-account list.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import (
    CorporateFleetAssignment,
    CorporateFleetVehicle,
)
from app.schemas.corporate_fleet_vehicle import (
    FleetAssignmentCreate,
    FleetAssignmentResponse,
    FleetSummaryResponse,
    FleetVehicleCreate,
    FleetVehicleResponse,
    FleetVehicleUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_vehicle_response(row: CorporateFleetVehicle) -> FleetVehicleResponse:
    return FleetVehicleResponse.model_validate(row)


def _to_assignment_response(row: CorporateFleetAssignment) -> FleetAssignmentResponse:
    return FleetAssignmentResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Fetch a vehicle by ID, verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == vehicle_id,
        CorporateFleetVehicle.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found.",
        )
    return row


async def _name_exists(
    db: AsyncSession,
    account_id: int,
    name: str,
    exclude_id: Optional[uuid.UUID] = None,
) -> bool:
    """Check whether a vehicle name is already taken for an account (case-insensitive).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        name: Vehicle name to check.
        exclude_id: Vehicle UUID to exclude from the check (for updates).

    Returns:
        True if a conflicting name exists.
    """
    normalised = name.strip().lower()
    conditions = [
        CorporateFleetVehicle.account_id == account_id,
    ]
    stmt = select(CorporateFleetVehicle).where(and_(*conditions))
    result = await db.execute(stmt)
    rows = result.scalars().all()

    for row in rows:
        if row.name.strip().lower() == normalised:
            if exclude_id is None or row.id != exclude_id:
                return True
    return False


# ---------------------------------------------------------------------------
# create_fleet_vehicle
# ---------------------------------------------------------------------------


async def create_fleet_vehicle(
    db: AsyncSession,
    account_id: int,
    payload: FleetVehicleCreate,
    created_by_id: Optional[int] = None,
) -> FleetVehicleResponse:
    """Create a new vehicle in the corporate fleet.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        payload: Vehicle creation data.
        created_by_id: ID of the user creating the record.

    Returns:
        ``FleetVehicleResponse`` for the new vehicle.

    Raises:
        HTTPException 409: A vehicle with the same name already exists for
            this account (case-insensitive).
    """
    if await _name_exists(db, account_id, payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A fleet vehicle named '{payload.name}' already exists for this account.",
        )

    vehicle = CorporateFleetVehicle(
        id=uuid.uuid4(),
        account_id=account_id,
        name=payload.name,
        vehicle_type=payload.vehicle_type,
        make=payload.make,
        model_name=payload.model_name,
        year=payload.year,
        license_plate=payload.license_plate,
        color=payload.color,
        capacity=payload.capacity,
        is_wav=payload.is_wav,
        notes=payload.notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return _to_vehicle_response(vehicle)


# ---------------------------------------------------------------------------
# get_fleet_vehicle
# ---------------------------------------------------------------------------


async def get_fleet_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> FleetVehicleResponse:
    """Return a single fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Returns:
        ``FleetVehicleResponse``.

    Raises:
        HTTPException 404: Vehicle not found or wrong account.
    """
    row = await _fetch_vehicle(db, account_id, vehicle_id)
    return _to_vehicle_response(row)


# ---------------------------------------------------------------------------
# list_fleet_vehicles
# ---------------------------------------------------------------------------


async def list_fleet_vehicles(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
    is_wav: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FleetVehicleResponse]:
    """Return a filtered, paginated list of fleet vehicles for an account.

    Results are sorted by name ascending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional filter on active status.
        is_wav: Optional filter on wheelchair-accessible status.
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``FleetVehicleResponse``.
    """
    conditions = [CorporateFleetVehicle.account_id == account_id]
    if is_active is not None:
        conditions.append(CorporateFleetVehicle.is_active == is_active)
    if is_wav is not None:
        conditions.append(CorporateFleetVehicle.is_wav == is_wav)

    stmt = (
        select(CorporateFleetVehicle)
        .where(and_(*conditions))
        .order_by(CorporateFleetVehicle.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_vehicle_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_fleet_vehicle
# ---------------------------------------------------------------------------


async def update_fleet_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    payload: FleetVehicleUpdate,
) -> FleetVehicleResponse:
    """Partially update a fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle to update.
        payload: Fields to update (None values are ignored).

    Returns:
        Updated ``FleetVehicleResponse``.

    Raises:
        HTTPException 404: Vehicle not found.
        HTTPException 409: Another vehicle with the new name already exists.
    """
    row = await _fetch_vehicle(db, account_id, vehicle_id)

    update_data = payload.model_dump(exclude_none=True)

    if "name" in update_data:
        new_name = update_data["name"]
        if new_name.strip().lower() != row.name.strip().lower():
            if await _name_exists(db, account_id, new_name, exclude_id=vehicle_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A fleet vehicle named '{new_name}' already exists for this account.",
                )

    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_vehicle_response(row)


# ---------------------------------------------------------------------------
# deactivate_fleet_vehicle
# ---------------------------------------------------------------------------


async def deactivate_fleet_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> FleetVehicleResponse:
    """Deactivate a fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Returns:
        Updated ``FleetVehicleResponse``.

    Raises:
        HTTPException 404: Vehicle not found.
        HTTPException 409: Vehicle is already inactive.
    """
    row = await _fetch_vehicle(db, account_id, vehicle_id)
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet vehicle is already inactive.",
        )
    row.is_active = False
    await db.commit()
    await db.refresh(row)
    return _to_vehicle_response(row)


# ---------------------------------------------------------------------------
# reactivate_fleet_vehicle
# ---------------------------------------------------------------------------


async def reactivate_fleet_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> FleetVehicleResponse:
    """Reactivate a previously deactivated fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Returns:
        Updated ``FleetVehicleResponse``.

    Raises:
        HTTPException 404: Vehicle not found.
        HTTPException 409: Vehicle is already active.
    """
    row = await _fetch_vehicle(db, account_id, vehicle_id)
    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet vehicle is already active.",
        )
    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return _to_vehicle_response(row)


# ---------------------------------------------------------------------------
# delete_fleet_vehicle
# ---------------------------------------------------------------------------


async def delete_fleet_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> None:
    """Hard-delete a fleet vehicle.

    The vehicle must be deactivated before deletion.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Raises:
        HTTPException 404: Vehicle not found.
        HTTPException 409: Vehicle is still active — deactivate first.
    """
    row = await _fetch_vehicle(db, account_id, vehicle_id)
    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active fleet vehicle. Deactivate it first.",
        )
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# assign_driver
# ---------------------------------------------------------------------------


async def assign_driver(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    payload: FleetAssignmentCreate,
    assigned_by_id: Optional[int] = None,
) -> FleetAssignmentResponse:
    """Assign a driver to a fleet vehicle.

    Any existing active assignment for the vehicle is deactivated first.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.
        payload: Assignment data (driver_profile_id, notes).
        assigned_by_id: ID of the user performing the assignment.

    Returns:
        ``FleetAssignmentResponse`` for the new active assignment.

    Raises:
        HTTPException 404: Vehicle not found.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    # Deactivate any existing active assignment
    existing_stmt = select(CorporateFleetAssignment).where(
        CorporateFleetAssignment.fleet_vehicle_id == vehicle_id,
        CorporateFleetAssignment.is_active == True,  # noqa: E712
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        existing.is_active = False

    assignment = CorporateFleetAssignment(
        id=uuid.uuid4(),
        fleet_vehicle_id=vehicle_id,
        account_id=account_id,
        driver_profile_id=payload.driver_profile_id,
        assigned_by_id=assigned_by_id,
        is_active=True,
        notes=payload.notes,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return _to_assignment_response(assignment)


# ---------------------------------------------------------------------------
# end_assignment
# ---------------------------------------------------------------------------


async def end_assignment(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> FleetAssignmentResponse:
    """End the active driver assignment for a fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Returns:
        Updated ``FleetAssignmentResponse`` (is_active=False).

    Raises:
        HTTPException 404: No active assignment found for this vehicle.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    stmt = select(CorporateFleetAssignment).where(
        CorporateFleetAssignment.fleet_vehicle_id == vehicle_id,
        CorporateFleetAssignment.account_id == account_id,
        CorporateFleetAssignment.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active assignment found for this vehicle.",
        )
    assignment.is_active = False
    await db.commit()
    await db.refresh(assignment)
    return _to_assignment_response(assignment)


# ---------------------------------------------------------------------------
# get_active_assignment
# ---------------------------------------------------------------------------


async def get_active_assignment(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> Optional[FleetAssignmentResponse]:
    """Return the current active assignment for a vehicle, or None.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.

    Returns:
        ``FleetAssignmentResponse`` or None if no active assignment.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    stmt = select(CorporateFleetAssignment).where(
        CorporateFleetAssignment.fleet_vehicle_id == vehicle_id,
        CorporateFleetAssignment.account_id == account_id,
        CorporateFleetAssignment.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _to_assignment_response(row)


# ---------------------------------------------------------------------------
# list_vehicle_assignments
# ---------------------------------------------------------------------------


async def list_vehicle_assignments(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[FleetAssignmentResponse]:
    """Return the full assignment history for a vehicle, newest-first.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the vehicle.
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``FleetAssignmentResponse``, newest first.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    stmt = (
        select(CorporateFleetAssignment)
        .where(
            CorporateFleetAssignment.fleet_vehicle_id == vehicle_id,
            CorporateFleetAssignment.account_id == account_id,
        )
        .order_by(CorporateFleetAssignment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_assignment_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_fleet_summary
# ---------------------------------------------------------------------------


async def get_fleet_summary(
    db: AsyncSession,
    account_id: int,
) -> FleetSummaryResponse:
    """Return aggregate fleet statistics for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``FleetSummaryResponse`` with counts and breakdown by vehicle type.
    """
    all_stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.account_id == account_id
    )
    all_result = await db.execute(all_stmt)
    all_vehicles = all_result.scalars().all()

    total = len(all_vehicles)
    active = sum(1 for v in all_vehicles if v.is_active)
    inactive = total - active
    wav_count = sum(1 for v in all_vehicles if v.is_wav and v.is_active)

    by_type: dict[str, int] = {}
    for v in all_vehicles:
        if v.is_active:
            key = v.vehicle_type or "other"
            by_type[key] = by_type.get(key, 0) + 1

    # Count active vehicles that have no active assignment
    active_vehicle_ids = [v.id for v in all_vehicles if v.is_active]
    assigned_ids: set = set()
    if active_vehicle_ids:
        assign_stmt = select(CorporateFleetAssignment).where(
            CorporateFleetAssignment.account_id == account_id,
            CorporateFleetAssignment.is_active == True,  # noqa: E712
            CorporateFleetAssignment.fleet_vehicle_id.in_(active_vehicle_ids),
        )
        assign_result = await db.execute(assign_stmt)
        assignments = assign_result.scalars().all()
        assigned_ids = {a.fleet_vehicle_id for a in assignments}

    unassigned_count = sum(
        1 for v_id in active_vehicle_ids if v_id not in assigned_ids
    )

    return FleetSummaryResponse(
        total_vehicles=total,
        active_vehicles=active,
        inactive_vehicles=inactive,
        wav_count=wav_count,
        unassigned_count=unassigned_count,
        by_type=by_type,
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FleetVehicleResponse]:
    """Return fleet vehicles across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``FleetVehicleResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateFleetVehicle.account_id == account_id)

    base = select(CorporateFleetVehicle)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetVehicle.account_id,
            CorporateFleetVehicle.name,
        )
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_vehicle_response(r) for r in rows]
