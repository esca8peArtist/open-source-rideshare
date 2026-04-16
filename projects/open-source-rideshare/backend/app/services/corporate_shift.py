"""Service layer for Corporate Shift-Based Ride Scheduling.

Companies with shift workers (healthcare, manufacturing, security) need
coordinated transportation to/from shift start and end times.  Admins define
named shifts with timing and location; assign employees to shifts with their
personal pickup addresses.

Public surface
--------------
create_shift(db, account_id, created_by_id, data) -> ShiftResponse
get_shift(db, shift_id, account_id) -> ShiftResponse
list_shifts(db, account_id, is_active) -> ShiftListResponse
update_shift(db, shift_id, account_id, data) -> ShiftResponse
deactivate_shift(db, shift_id, account_id) -> ShiftResponse
reactivate_shift(db, shift_id, account_id) -> ShiftResponse
delete_shift(db, shift_id, account_id) -> None
assign_member(db, shift_id, account_id, data, assigned_by_id) -> AssignmentResponse
get_assignment(db, assignment_id) -> AssignmentResponse
update_assignment(db, assignment_id, data) -> AssignmentResponse
remove_assignment(db, assignment_id) -> None
list_shift_members(db, shift_id, account_id, is_active) -> AssignmentListResponse
get_member_shifts(db, account_id, member_id, is_active) -> AssignmentListResponse
get_shift_summary(db, shift_id, account_id) -> ShiftSummaryResponse
list_all_platform(db, account_id) -> ShiftListResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment
from app.schemas.corporate_shift import (
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentResponse,
    AssignmentUpdate,
    ShiftCreate,
    ShiftListResponse,
    ShiftResponse,
    ShiftSummaryResponse,
    ShiftUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_shift_response(shift: CorporateShift) -> ShiftResponse:
    """Convert a CorporateShift model instance to ShiftResponse."""
    return ShiftResponse(
        id=shift.id,
        account_id=shift.account_id,
        name=shift.name,
        description=shift.description,
        work_location_name=shift.work_location_name,
        work_address_line1=shift.work_address_line1,
        work_address_line2=shift.work_address_line2,
        work_city=shift.work_city,
        work_state=shift.work_state,
        work_country=shift.work_country,
        work_postal_code=shift.work_postal_code,
        work_latitude=shift.work_latitude,
        work_longitude=shift.work_longitude,
        shift_start_time=shift.shift_start_time,
        shift_end_time=shift.shift_end_time,
        days_of_week=shift.days_of_week or [],
        is_active=shift.is_active,
        created_by_id=shift.created_by_id,
        created_at=shift.created_at,
        updated_at=shift.updated_at,
    )


def _to_assignment_response(assignment: CorporateShiftAssignment) -> AssignmentResponse:
    """Convert a CorporateShiftAssignment model instance to AssignmentResponse."""
    return AssignmentResponse(
        id=assignment.id,
        shift_id=assignment.shift_id,
        member_id=assignment.member_id,
        pickup_address_line1=assignment.pickup_address_line1,
        pickup_address_line2=assignment.pickup_address_line2,
        pickup_city=assignment.pickup_city,
        pickup_state=assignment.pickup_state,
        pickup_country=assignment.pickup_country,
        pickup_postal_code=assignment.pickup_postal_code,
        pickup_latitude=assignment.pickup_latitude,
        pickup_longitude=assignment.pickup_longitude,
        auto_request_rides=assignment.auto_request_rides,
        advance_booking_minutes=assignment.advance_booking_minutes,
        is_active=assignment.is_active,
        assigned_by_id=assignment.assigned_by_id,
        notes=assignment.notes,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


async def _fetch_shift(
    db: AsyncSession, shift_id: int, account_id: int
) -> Optional[CorporateShift]:
    """Return the shift row for an account, or None."""
    result = await db.execute(
        select(CorporateShift).where(
            CorporateShift.id == shift_id,
            CorporateShift.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _fetch_assignment(
    db: AsyncSession, assignment_id: int
) -> Optional[CorporateShiftAssignment]:
    """Return the assignment row by ID, or None."""
    result = await db.execute(
        select(CorporateShiftAssignment).where(
            CorporateShiftAssignment.id == assignment_id
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Shift management
# ---------------------------------------------------------------------------


async def create_shift(
    db: AsyncSession,
    account_id: int,
    created_by_id: int,
    data: ShiftCreate,
) -> ShiftResponse:
    """Create a new corporate shift.

    A shift starts active.  Returns 409 if an active shift with the same name
    already exists for this account.

    Args:
        db:             Async database session.
        account_id:     Corporate account identifier.
        created_by_id:  ID of the admin creating the shift.
        data:           Validated creation payload.

    Returns:
        ShiftResponse for the newly created shift.

    Raises:
        HTTP 409: Active shift with same name already exists for account.
    """
    existing = await db.execute(
        select(CorporateShift).where(
            CorporateShift.account_id == account_id,
            CorporateShift.name == data.name,
            CorporateShift.is_active.is_(True),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active shift with this name already exists for the account.",
        )

    shift = CorporateShift(
        account_id=account_id,
        created_by_id=created_by_id,
        name=data.name,
        description=data.description,
        work_location_name=data.work_location_name,
        work_address_line1=data.work_address_line1,
        work_address_line2=data.work_address_line2,
        work_city=data.work_city,
        work_state=data.work_state,
        work_country=data.work_country,
        work_postal_code=data.work_postal_code,
        shift_start_time=data.shift_start_time,
        shift_end_time=data.shift_end_time,
        days_of_week=data.days_of_week,
        is_active=True,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return _to_shift_response(shift)


async def get_shift(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
) -> ShiftResponse:
    """Return a single shift by ID.

    Args:
        db:         Async database session.
        shift_id:   ID of the shift to fetch.
        account_id: Corporate account identifier.

    Returns:
        ShiftResponse.

    Raises:
        HTTP 404: Shift not found or does not belong to the account.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )
    return _to_shift_response(shift)


async def list_shifts(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> ShiftListResponse:
    """List shifts for a corporate account with optional active filter.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        is_active:  Optional filter: True = active only, False = inactive only.

    Returns:
        ShiftListResponse with total count and items.
    """
    query = select(CorporateShift).where(
        CorporateShift.account_id == account_id
    )
    if is_active is not None:
        query = query.where(CorporateShift.is_active.is_(is_active))

    result = await db.execute(query.order_by(CorporateShift.name))
    shifts = list(result.scalars().all())

    return ShiftListResponse(
        total=len(shifts),
        items=[_to_shift_response(s) for s in shifts],
    )


async def update_shift(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
    data: ShiftUpdate,
) -> ShiftResponse:
    """Partially update a corporate shift.

    Only fields explicitly supplied in the request body are written.  Raises
    409 if the new name collides with another shift in the same account.

    Args:
        db:         Async database session.
        shift_id:   ID of the shift to update.
        account_id: Corporate account identifier.
        data:       Validated update payload.

    Returns:
        Updated ShiftResponse.

    Raises:
        HTTP 404: Shift not found.
        HTTP 409: Name collision with another shift in the same account.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )

    payload = data.model_dump(exclude_unset=True)

    if "name" in payload and payload["name"] != shift.name:
        collision = await db.execute(
            select(CorporateShift).where(
                CorporateShift.account_id == account_id,
                CorporateShift.name == payload["name"],
                CorporateShift.id != shift_id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another shift with this name already exists for the account.",
            )

    for field, value in payload.items():
        setattr(shift, field, value)

    await db.commit()
    await db.refresh(shift)
    return _to_shift_response(shift)


async def deactivate_shift(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
) -> ShiftResponse:
    """Deactivate a corporate shift.

    Args:
        db:         Async database session.
        shift_id:   ID of the shift to deactivate.
        account_id: Corporate account identifier.

    Returns:
        Updated ShiftResponse with is_active=False.

    Raises:
        HTTP 404: Shift not found.
        HTTP 409: Shift is already inactive.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )
    if not shift.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shift is already inactive.",
        )

    shift.is_active = False
    await db.commit()
    await db.refresh(shift)
    return _to_shift_response(shift)


async def reactivate_shift(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
) -> ShiftResponse:
    """Reactivate a corporate shift.

    Args:
        db:         Async database session.
        shift_id:   ID of the shift to reactivate.
        account_id: Corporate account identifier.

    Returns:
        Updated ShiftResponse with is_active=True.

    Raises:
        HTTP 404: Shift not found.
        HTTP 409: Shift is already active.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )
    if shift.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shift is already active.",
        )

    shift.is_active = True
    await db.commit()
    await db.refresh(shift)
    return _to_shift_response(shift)


async def delete_shift(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
) -> None:
    """Delete a corporate shift and all its assignments (cascade).

    Args:
        db:         Async database session.
        shift_id:   ID of the shift to delete.
        account_id: Corporate account identifier.

    Raises:
        HTTP 404: Shift not found.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )

    await db.delete(shift)
    await db.commit()


# ---------------------------------------------------------------------------
# Assignment management
# ---------------------------------------------------------------------------


async def assign_member(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
    data: AssignmentCreate,
    assigned_by_id: int,
) -> AssignmentResponse:
    """Assign a member to a corporate shift.

    Args:
        db:             Async database session.
        shift_id:       ID of the shift.
        account_id:     Corporate account identifier (used to validate shift).
        data:           Validated assignment creation payload.
        assigned_by_id: ID of the admin creating the assignment.

    Returns:
        AssignmentResponse for the new assignment.

    Raises:
        HTTP 404: Shift not found for this account.
        HTTP 409: Member already has an active assignment to this shift.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )

    existing = await db.execute(
        select(CorporateShiftAssignment).where(
            CorporateShiftAssignment.shift_id == shift_id,
            CorporateShiftAssignment.member_id == data.member_id,
            CorporateShiftAssignment.is_active.is_(True),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member already has an active assignment to this shift.",
        )

    assignment = CorporateShiftAssignment(
        shift_id=shift_id,
        member_id=data.member_id,
        pickup_address_line1=data.pickup_address_line1,
        pickup_address_line2=data.pickup_address_line2,
        pickup_city=data.pickup_city,
        pickup_state=data.pickup_state,
        pickup_country=data.pickup_country,
        pickup_postal_code=data.pickup_postal_code,
        auto_request_rides=data.auto_request_rides,
        advance_booking_minutes=data.advance_booking_minutes,
        is_active=True,
        assigned_by_id=assigned_by_id,
        notes=data.notes,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return _to_assignment_response(assignment)


async def get_assignment(
    db: AsyncSession,
    assignment_id: int,
) -> AssignmentResponse:
    """Return a single assignment by ID.

    Args:
        db:             Async database session.
        assignment_id:  ID of the assignment to fetch.

    Returns:
        AssignmentResponse.

    Raises:
        HTTP 404: Assignment not found.
    """
    assignment = await _fetch_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shift assignment not found.",
        )
    return _to_assignment_response(assignment)


async def update_assignment(
    db: AsyncSession,
    assignment_id: int,
    data: AssignmentUpdate,
) -> AssignmentResponse:
    """Partially update a shift assignment.

    Only fields explicitly supplied in the request body are written.

    Args:
        db:             Async database session.
        assignment_id:  ID of the assignment to update.
        data:           Validated update payload.

    Returns:
        Updated AssignmentResponse.

    Raises:
        HTTP 404: Assignment not found.
    """
    assignment = await _fetch_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shift assignment not found.",
        )

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(assignment, field, value)

    await db.commit()
    await db.refresh(assignment)
    return _to_assignment_response(assignment)


async def remove_assignment(
    db: AsyncSession,
    assignment_id: int,
) -> None:
    """Hard-delete a shift assignment.

    Args:
        db:             Async database session.
        assignment_id:  ID of the assignment to remove.

    Raises:
        HTTP 404: Assignment not found.
    """
    assignment = await _fetch_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shift assignment not found.",
        )

    await db.delete(assignment)
    await db.commit()


async def list_shift_members(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
    is_active: Optional[bool] = None,
) -> AssignmentListResponse:
    """List all member assignments for a shift.

    Args:
        db:         Async database session.
        shift_id:   ID of the shift.
        account_id: Corporate account identifier (used to validate shift).
        is_active:  Optional filter: True = active only, False = inactive only.

    Returns:
        AssignmentListResponse with total count and items.

    Raises:
        HTTP 404: Shift not found.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )

    query = select(CorporateShiftAssignment).where(
        CorporateShiftAssignment.shift_id == shift_id
    )
    if is_active is not None:
        query = query.where(CorporateShiftAssignment.is_active.is_(is_active))

    result = await db.execute(query.order_by(CorporateShiftAssignment.id))
    assignments = list(result.scalars().all())

    return AssignmentListResponse(
        total=len(assignments),
        items=[_to_assignment_response(a) for a in assignments],
    )


async def get_member_shifts(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    is_active: Optional[bool] = None,
) -> AssignmentListResponse:
    """Return all shift assignments for a member within a corporate account.

    Joins through corporate_shifts to scope to the correct account.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        member_id:  ID of the corporate account member.
        is_active:  Optional filter: True = active only, False = inactive only.

    Returns:
        AssignmentListResponse with total count and items.
    """
    query = (
        select(CorporateShiftAssignment)
        .join(CorporateShift, CorporateShiftAssignment.shift_id == CorporateShift.id)
        .where(
            CorporateShift.account_id == account_id,
            CorporateShiftAssignment.member_id == member_id,
        )
    )
    if is_active is not None:
        query = query.where(CorporateShiftAssignment.is_active.is_(is_active))

    result = await db.execute(query.order_by(CorporateShiftAssignment.id))
    assignments = list(result.scalars().all())

    return AssignmentListResponse(
        total=len(assignments),
        items=[_to_assignment_response(a) for a in assignments],
    )


async def get_shift_summary(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
) -> ShiftSummaryResponse:
    """Return a lightweight summary of a corporate shift.

    Args:
        db:         Async database session.
        shift_id:   ID of the shift.
        account_id: Corporate account identifier.

    Returns:
        ShiftSummaryResponse with member counts.

    Raises:
        HTTP 404: Shift not found.
    """
    shift = await _fetch_shift(db, shift_id, account_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate shift not found.",
        )

    result = await db.execute(
        select(CorporateShiftAssignment).where(
            CorporateShiftAssignment.shift_id == shift_id
        )
    )
    assignments = list(result.scalars().all())

    active_members = sum(1 for a in assignments if a.is_active)
    inactive_members = sum(1 for a in assignments if not a.is_active)
    members_with_auto_request = sum(
        1 for a in assignments if a.is_active and a.auto_request_rides
    )

    return ShiftSummaryResponse(
        shift_id=shift.id,
        name=shift.name,
        is_active=shift.is_active,
        total_members=len(assignments),
        active_members=active_members,
        inactive_members=inactive_members,
        members_with_auto_request=members_with_auto_request,
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> ShiftListResponse:
    """List all corporate shifts across all accounts (platform admin).

    Args:
        db:         Async database session.
        account_id: Optional filter to a specific corporate account.

    Returns:
        ShiftListResponse with total count and items.
    """
    query = select(CorporateShift)
    if account_id is not None:
        query = query.where(CorporateShift.account_id == account_id)

    result = await db.execute(
        query.order_by(CorporateShift.account_id, CorporateShift.name)
    )
    shifts = list(result.scalars().all())

    return ShiftListResponse(
        total=len(shifts),
        items=[_to_shift_response(s) for s in shifts],
    )
