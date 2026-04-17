"""Service layer for Corporate Fleet Driver Assignments.

Fleet admins assign corporate account members to fleet vehicles, tracking
who is the primary, secondary, pool, or temporary driver of each vehicle
and recording the full assignment history.

Public functions
----------------
create_assignment           — create an assignment, enforce primary uniqueness.
get_assignment              — fetch one assignment (404 if missing or wrong account).
get_vehicle_assignments     — all assignments for a vehicle, optional status filter.
get_user_assignments        — all assignments for a user.
get_active_primary_driver   — active primary driver assignment for a vehicle or None.
update_assignment           — partial update (end_date, notes, status).
activate_assignment         — pending → active.
suspend_assignment          — active → suspended.
end_assignment              — active/suspended → inactive, set end_date.
delete_assignment           — only if inactive, raises 409 otherwise.
get_account_assignments     — all assignments for an account.
list_all_assignments        — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_fleet_driver_assignment import (
    CorporateFleetDriverAssignment,
    FleetDriverAssignmentStatus,
    FleetDriverAssignmentType,
)
from app.schemas.corporate_fleet_driver_assignment import (
    DriverAssignmentCreate,
    DriverAssignmentResponse,
    DriverAssignmentUpdate,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateFleetDriverAssignment) -> DriverAssignmentResponse:
    return DriverAssignmentResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
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
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == vehicle_id,
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


async def _fetch_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
) -> CorporateFleetDriverAssignment:
    """Return a driver assignment verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.

    Returns:
        ``CorporateFleetDriverAssignment`` ORM instance.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
    """
    stmt = select(CorporateFleetDriverAssignment).where(
        CorporateFleetDriverAssignment.id == assignment_id,
        CorporateFleetDriverAssignment.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver assignment not found.",
        )
    return row


# ---------------------------------------------------------------------------
# create_assignment
# ---------------------------------------------------------------------------


async def create_assignment(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    user_id: int,
    assignment_type: FleetDriverAssignmentType,
    start_date: date,
    authorized_by_user_id: Optional[int] = None,
    end_date: Optional[date] = None,
    notes: Optional[str] = None,
) -> DriverAssignmentResponse:
    """Create a new driver assignment for a corporate fleet vehicle.

    Enforces that at most one active primary driver exists per vehicle.
    When a new primary assignment is created, any existing active primary
    is ended (status → inactive, end_date → today).

    Also enforces that at most two active secondary drivers exist per vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.
        user_id: ID of the user being assigned.
        assignment_type: Role classification for this assignment.
        start_date: Date the assignment becomes effective.
        authorized_by_user_id: ID of the user authorizing the assignment.
        end_date: Optional explicit end date.
        notes: Optional free-text notes.

    Returns:
        ``DriverAssignmentResponse`` for the new assignment.

    Raises:
        HTTPException 404: Vehicle not found for this account.
        HTTPException 409: Secondary driver limit (2) would be exceeded.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    if assignment_type == FleetDriverAssignmentType.primary:
        # End any existing active primary assignment for this vehicle.
        existing_primary_stmt = select(CorporateFleetDriverAssignment).where(
            CorporateFleetDriverAssignment.vehicle_id == vehicle_id,
            CorporateFleetDriverAssignment.account_id == account_id,
            CorporateFleetDriverAssignment.assignment_type == FleetDriverAssignmentType.primary,
            CorporateFleetDriverAssignment.status == FleetDriverAssignmentStatus.active,
        )
        existing_result = await db.execute(existing_primary_stmt)
        existing_primary = existing_result.scalar_one_or_none()
        if existing_primary is not None:
            existing_primary.status = FleetDriverAssignmentStatus.inactive
            existing_primary.end_date = date.today()

    elif assignment_type == FleetDriverAssignmentType.secondary:
        # Enforce maximum of 2 active secondary drivers per vehicle.
        secondary_stmt = select(CorporateFleetDriverAssignment).where(
            CorporateFleetDriverAssignment.vehicle_id == vehicle_id,
            CorporateFleetDriverAssignment.account_id == account_id,
            CorporateFleetDriverAssignment.assignment_type == FleetDriverAssignmentType.secondary,
            CorporateFleetDriverAssignment.status == FleetDriverAssignmentStatus.active,
        )
        secondary_result = await db.execute(secondary_stmt)
        active_secondary_count = len(secondary_result.scalars().all())
        if active_secondary_count >= 2:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A vehicle may have at most 2 active secondary drivers.",
            )

    # Determine initial status: pending if start_date is in the future.
    initial_status = (
        FleetDriverAssignmentStatus.pending
        if start_date > date.today()
        else FleetDriverAssignmentStatus.active
    )

    assignment = CorporateFleetDriverAssignment(
        id=uuid.uuid4(),
        vehicle_id=vehicle_id,
        account_id=account_id,
        user_id=user_id,
        assignment_type=assignment_type,
        status=initial_status,
        start_date=start_date,
        end_date=end_date,
        authorized_by_user_id=authorized_by_user_id,
        notes=notes,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return _to_response(assignment)


# ---------------------------------------------------------------------------
# get_assignment
# ---------------------------------------------------------------------------


async def get_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
) -> DriverAssignmentResponse:
    """Return a single driver assignment.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.

    Returns:
        ``DriverAssignmentResponse``.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
    """
    row = await _fetch_assignment(db, account_id, assignment_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# get_vehicle_assignments
# ---------------------------------------------------------------------------


async def get_vehicle_assignments(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    *,
    status: Optional[FleetDriverAssignmentStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[DriverAssignmentResponse]:
    """Return all driver assignments for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.
        status: Optional filter by assignment status.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``DriverAssignmentResponse``.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    conditions = [
        CorporateFleetDriverAssignment.vehicle_id == vehicle_id,
        CorporateFleetDriverAssignment.account_id == account_id,
    ]
    if status is not None:
        conditions.append(CorporateFleetDriverAssignment.status == status)

    stmt = (
        select(CorporateFleetDriverAssignment)
        .where(and_(*conditions))
        .order_by(CorporateFleetDriverAssignment.start_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_user_assignments
# ---------------------------------------------------------------------------


async def get_user_assignments(
    db: AsyncSession,
    user_id: int,
    *,
    active_only: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> List[DriverAssignmentResponse]:
    """Return all driver assignments for a specific user.

    Args:
        db: Async SQLAlchemy session.
        user_id: ID of the user.
        active_only: If True, only return active assignments.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``DriverAssignmentResponse``.
    """
    conditions = [CorporateFleetDriverAssignment.user_id == user_id]
    if active_only:
        conditions.append(
            CorporateFleetDriverAssignment.status == FleetDriverAssignmentStatus.active
        )

    stmt = (
        select(CorporateFleetDriverAssignment)
        .where(and_(*conditions))
        .order_by(CorporateFleetDriverAssignment.start_date.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_active_primary_driver
# ---------------------------------------------------------------------------


async def get_active_primary_driver(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> Optional[DriverAssignmentResponse]:
    """Return the active primary driver assignment for a vehicle, or None.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``DriverAssignmentResponse`` if an active primary driver exists, else None.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, vehicle_id)

    stmt = select(CorporateFleetDriverAssignment).where(
        CorporateFleetDriverAssignment.vehicle_id == vehicle_id,
        CorporateFleetDriverAssignment.account_id == account_id,
        CorporateFleetDriverAssignment.assignment_type == FleetDriverAssignmentType.primary,
        CorporateFleetDriverAssignment.status == FleetDriverAssignmentStatus.active,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return _to_response(row) if row is not None else None


# ---------------------------------------------------------------------------
# update_assignment
# ---------------------------------------------------------------------------


async def update_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
    data: DriverAssignmentUpdate,
) -> DriverAssignmentResponse:
    """Partially update a driver assignment.

    Only ``end_date``, ``notes``, and ``status`` may be updated via this
    function.  Use the dedicated action endpoints for status transitions.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``DriverAssignmentResponse``.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
    """
    row = await _fetch_assignment(db, account_id, assignment_id)

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# activate_assignment
# ---------------------------------------------------------------------------


async def activate_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
) -> DriverAssignmentResponse:
    """Transition a pending assignment to active.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.

    Returns:
        Updated ``DriverAssignmentResponse``.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
        HTTPException 409: Assignment is not in pending status.
    """
    row = await _fetch_assignment(db, account_id, assignment_id)

    if row.status != FleetDriverAssignmentStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Assignment cannot be activated from status '{row.status.value}'.",
        )

    row.status = FleetDriverAssignmentStatus.active
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# suspend_assignment
# ---------------------------------------------------------------------------


async def suspend_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
) -> DriverAssignmentResponse:
    """Transition an active assignment to suspended.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.

    Returns:
        Updated ``DriverAssignmentResponse``.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
        HTTPException 409: Assignment is not in active status.
    """
    row = await _fetch_assignment(db, account_id, assignment_id)

    if row.status != FleetDriverAssignmentStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Assignment cannot be suspended from status '{row.status.value}'.",
        )

    row.status = FleetDriverAssignmentStatus.suspended
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# end_assignment
# ---------------------------------------------------------------------------


async def end_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
    end_date: Optional[date] = None,
) -> DriverAssignmentResponse:
    """Transition an active or suspended assignment to inactive.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.
        end_date: Explicit end date; defaults to today if not provided.

    Returns:
        Updated ``DriverAssignmentResponse``.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
        HTTPException 409: Assignment is not in active or suspended status.
    """
    row = await _fetch_assignment(db, account_id, assignment_id)

    if row.status not in (
        FleetDriverAssignmentStatus.active,
        FleetDriverAssignmentStatus.suspended,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Assignment cannot be ended from status '{row.status.value}'.",
        )

    row.status = FleetDriverAssignmentStatus.inactive
    row.end_date = end_date if end_date is not None else date.today()
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# delete_assignment
# ---------------------------------------------------------------------------


async def delete_assignment(
    db: AsyncSession,
    account_id: int,
    assignment_id: uuid.UUID,
) -> None:
    """Delete a driver assignment record.

    Only inactive assignments may be deleted.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        assignment_id: UUID of the driver assignment.

    Raises:
        HTTPException 404: Assignment not found or wrong account.
        HTTPException 409: Assignment is not inactive.
    """
    row = await _fetch_assignment(db, account_id, assignment_id)

    if row.status != FleetDriverAssignmentStatus.inactive:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only inactive assignments may be deleted. "
                f"Current status: '{row.status.value}'."
            ),
        )

    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# get_account_assignments
# ---------------------------------------------------------------------------


async def get_account_assignments(
    db: AsyncSession,
    account_id: int,
    *,
    active_only: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> List[DriverAssignmentResponse]:
    """Return all driver assignments for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        active_only: If True, only return active assignments.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``DriverAssignmentResponse``.
    """
    conditions = [CorporateFleetDriverAssignment.account_id == account_id]
    if active_only:
        conditions.append(
            CorporateFleetDriverAssignment.status == FleetDriverAssignmentStatus.active
        )

    stmt = (
        select(CorporateFleetDriverAssignment)
        .where(and_(*conditions))
        .order_by(CorporateFleetDriverAssignment.start_date.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_all_assignments
# ---------------------------------------------------------------------------


async def list_all_assignments(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[DriverAssignmentResponse]:
    """Return driver assignments across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``DriverAssignmentResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateFleetDriverAssignment.account_id == account_id)

    base = select(CorporateFleetDriverAssignment)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetDriverAssignment.account_id,
            CorporateFleetDriverAssignment.start_date.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
