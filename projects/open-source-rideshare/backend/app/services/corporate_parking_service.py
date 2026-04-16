"""Service layer for Corporate Parking Management.

Enterprise accounts define named parking facilities, add individual spots to
each facility, and assign spots to employees.

Public functions
----------------
create_facility         — create a facility for the account (409 on duplicate name).
get_facility            — fetch one facility (404 if missing or wrong account).
list_facilities         — filtered, paginated list for an account.
update_facility         — partial update (404; 409 on name collision).
deactivate_facility     — soft-delete (409 if already inactive).
add_spot                — add a spot to a facility (404 facility; 409 duplicate identifier).
get_spot                — fetch one spot (404 if missing or wrong account).
list_spots              — filtered list by facility / type / assigned / active.
assign_spot_to_member   — assign a spot to an employee (409 if spot already assigned).
end_assignment          — end active assignment for a spot (404 if no active assignment).
get_member_parking      — return member's active parking assignment(s).
get_facility_summary    — aggregate stats for a facility.
list_all_platform       — platform-admin cross-account listing of facilities.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_parking import (
    CorporateParkingAssignment,
    CorporateParkingFacility,
    CorporateParkingSpot,
    SpotType,
)
from app.schemas.corporate_parking import (
    AssignmentCreate,
    AssignmentResponse,
    FacilityCreate,
    FacilityResponse,
    FacilitySummaryResponse,
    FacilityUpdate,
    SpotCreate,
    SpotResponse,
    SpotUpdate,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_facility(row: CorporateParkingFacility) -> FacilityResponse:
    return FacilityResponse.model_validate(row)


def _to_spot(row: CorporateParkingSpot) -> SpotResponse:
    return SpotResponse.model_validate(row)


def _to_assignment(row: CorporateParkingAssignment) -> AssignmentResponse:
    return AssignmentResponse.model_validate(row)


async def _fetch_facility(
    db: AsyncSession,
    account_id: int,
    facility_id: uuid.UUID,
) -> CorporateParkingFacility:
    """Return a facility verifying account ownership.

    Raises:
        HTTPException 404: Facility not found or belongs to a different account.
    """
    stmt = select(CorporateParkingFacility).where(
        CorporateParkingFacility.id == facility_id,
        CorporateParkingFacility.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking facility not found.",
        )
    return row


async def _fetch_spot(
    db: AsyncSession,
    account_id: int,
    spot_id: uuid.UUID,
) -> CorporateParkingSpot:
    """Return a spot verifying account ownership.

    Raises:
        HTTPException 404: Spot not found or belongs to a different account.
    """
    stmt = select(CorporateParkingSpot).where(
        CorporateParkingSpot.id == spot_id,
        CorporateParkingSpot.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking spot not found.",
        )
    return row


# ---------------------------------------------------------------------------
# Facility CRUD
# ---------------------------------------------------------------------------


async def create_facility(
    db: AsyncSession,
    account_id: int,
    data: FacilityCreate,
    created_by_id: Optional[int] = None,
) -> FacilityResponse:
    """Create a new parking facility for the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Facility creation payload.
        created_by_id: User ID of the admin creating the record.

    Returns:
        ``FacilityResponse`` for the created facility.

    Raises:
        HTTPException 409: A facility with the same name already exists for this account.
    """
    # Check for duplicate name
    stmt = select(CorporateParkingFacility).where(
        CorporateParkingFacility.account_id == account_id,
        CorporateParkingFacility.name == data.name,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A parking facility named '{data.name}' already exists for this account.",
        )

    facility = CorporateParkingFacility(
        account_id=account_id,
        name=data.name,
        description=data.description,
        address_line1=data.address_line1,
        address_line2=data.address_line2,
        city=data.city,
        state=data.state,
        zip_code=data.zip_code,
        lat=data.lat,
        lng=data.lng,
        facility_type=data.facility_type,
        notes=data.notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(facility)
    await db.flush()
    await db.refresh(facility)
    return _to_facility(facility)


async def get_facility(
    db: AsyncSession,
    facility_id: uuid.UUID,
    account_id: int,
) -> FacilityResponse:
    """Fetch a single parking facility by ID.

    Args:
        db: Async SQLAlchemy session.
        facility_id: UUID of the facility.
        account_id: Corporate account ID for ownership verification.

    Returns:
        ``FacilityResponse``.

    Raises:
        HTTPException 404: Facility not found or belongs to a different account.
    """
    row = await _fetch_facility(db, account_id, facility_id)
    return _to_facility(row)


async def list_facilities(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[FacilityResponse]:
    """Return a filtered, paginated list of parking facilities for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional filter — True/False/None (all).
        skip: Pagination offset.
        limit: Maximum records to return.

    Returns:
        List of ``FacilityResponse``.
    """
    stmt = select(CorporateParkingFacility).where(
        CorporateParkingFacility.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateParkingFacility.is_active == is_active)
    stmt = stmt.order_by(CorporateParkingFacility.name).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return [_to_facility(r) for r in result.scalars().all()]


async def update_facility(
    db: AsyncSession,
    facility_id: uuid.UUID,
    account_id: int,
    data: FacilityUpdate,
) -> FacilityResponse:
    """Partially update a parking facility.

    Args:
        db: Async SQLAlchemy session.
        facility_id: UUID of the facility to update.
        account_id: Corporate account ID.
        data: Partial update payload.

    Returns:
        Updated ``FacilityResponse``.

    Raises:
        HTTPException 404: Facility not found.
        HTTPException 409: Name collision with another facility in the account.
    """
    facility = await _fetch_facility(db, account_id, facility_id)

    if data.name is not None and data.name != facility.name:
        stmt = select(CorporateParkingFacility).where(
            CorporateParkingFacility.account_id == account_id,
            CorporateParkingFacility.name == data.name,
            CorporateParkingFacility.id != facility_id,
        )
        collision = (await db.execute(stmt)).scalar_one_or_none()
        if collision is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A parking facility named '{data.name}' already exists for this account.",
            )
        facility.name = data.name

    if data.description is not None:
        facility.description = data.description
    if data.address_line1 is not None:
        facility.address_line1 = data.address_line1
    if data.address_line2 is not None:
        facility.address_line2 = data.address_line2
    if data.city is not None:
        facility.city = data.city
    if data.state is not None:
        facility.state = data.state
    if data.zip_code is not None:
        facility.zip_code = data.zip_code
    if data.lat is not None:
        facility.lat = data.lat
    if data.lng is not None:
        facility.lng = data.lng
    if data.facility_type is not None:
        facility.facility_type = data.facility_type
    if data.notes is not None:
        facility.notes = data.notes

    await db.flush()
    await db.refresh(facility)
    return _to_facility(facility)


async def deactivate_facility(
    db: AsyncSession,
    facility_id: uuid.UUID,
    account_id: int,
) -> FacilityResponse:
    """Soft-delete a parking facility.

    Args:
        db: Async SQLAlchemy session.
        facility_id: UUID of the facility.
        account_id: Corporate account ID.

    Returns:
        Updated ``FacilityResponse`` with is_active=False.

    Raises:
        HTTPException 404: Facility not found.
        HTTPException 409: Facility is already inactive.
    """
    facility = await _fetch_facility(db, account_id, facility_id)
    if not facility.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parking facility is already inactive.",
        )
    facility.is_active = False
    await db.flush()
    await db.refresh(facility)
    return _to_facility(facility)


# ---------------------------------------------------------------------------
# Spot CRUD
# ---------------------------------------------------------------------------


async def add_spot(
    db: AsyncSession,
    account_id: int,
    data: SpotCreate,
    created_by_id: Optional[int] = None,
) -> SpotResponse:
    """Add a parking spot to a facility.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Spot creation payload.
        created_by_id: Optional user ID of the admin adding the spot (unused in model but available for audit).

    Returns:
        ``SpotResponse`` for the created spot.

    Raises:
        HTTPException 404: Facility not found or wrong account.
        HTTPException 409: A spot with the same identifier already exists in this facility.
    """
    # Verify facility belongs to account
    await _fetch_facility(db, account_id, data.facility_id)

    # Check for duplicate spot identifier in the same facility
    stmt = select(CorporateParkingSpot).where(
        CorporateParkingSpot.facility_id == data.facility_id,
        CorporateParkingSpot.spot_identifier == data.spot_identifier,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Spot '{data.spot_identifier}' already exists in this facility.",
        )

    spot = CorporateParkingSpot(
        account_id=account_id,
        facility_id=data.facility_id,
        spot_identifier=data.spot_identifier,
        spot_type=data.spot_type,
        floor_level=data.floor_level,
        is_assigned=False,
        notes=data.notes,
        is_active=True,
    )
    db.add(spot)
    await db.flush()
    await db.refresh(spot)
    return _to_spot(spot)


async def get_spot(
    db: AsyncSession,
    spot_id: uuid.UUID,
    account_id: int,
) -> SpotResponse:
    """Fetch a single parking spot by ID.

    Args:
        db: Async SQLAlchemy session.
        spot_id: UUID of the spot.
        account_id: Corporate account ID.

    Returns:
        ``SpotResponse``.

    Raises:
        HTTPException 404: Spot not found or wrong account.
    """
    row = await _fetch_spot(db, account_id, spot_id)
    return _to_spot(row)


async def list_spots(
    db: AsyncSession,
    account_id: int,
    facility_id: Optional[uuid.UUID] = None,
    spot_type: Optional[SpotType] = None,
    is_assigned: Optional[bool] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 200,
) -> List[SpotResponse]:
    """Return a filtered, paginated list of parking spots for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        facility_id: Optional facility filter.
        spot_type: Optional spot type filter.
        is_assigned: Optional assignment status filter.
        is_active: Optional active status filter.
        skip: Pagination offset.
        limit: Maximum records to return.

    Returns:
        List of ``SpotResponse``.
    """
    stmt = select(CorporateParkingSpot).where(
        CorporateParkingSpot.account_id == account_id
    )
    if facility_id is not None:
        stmt = stmt.where(CorporateParkingSpot.facility_id == facility_id)
    if spot_type is not None:
        stmt = stmt.where(CorporateParkingSpot.spot_type == spot_type)
    if is_assigned is not None:
        stmt = stmt.where(CorporateParkingSpot.is_assigned == is_assigned)
    if is_active is not None:
        stmt = stmt.where(CorporateParkingSpot.is_active == is_active)
    stmt = stmt.order_by(CorporateParkingSpot.spot_identifier).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return [_to_spot(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Assignment management
# ---------------------------------------------------------------------------


async def assign_spot_to_member(
    db: AsyncSession,
    account_id: int,
    spot_id: uuid.UUID,
    data: AssignmentCreate,
    assigned_by_id: Optional[int] = None,
) -> AssignmentResponse:
    """Assign a parking spot to a corporate member.

    Only one active assignment may exist per spot at a time.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        spot_id: UUID of the spot to assign.
        data: Assignment creation payload.
        assigned_by_id: User ID of the admin creating the assignment.

    Returns:
        ``AssignmentResponse`` for the new assignment.

    Raises:
        HTTPException 404: Spot not found or wrong account.
        HTTPException 409: Spot already has an active assignment.
    """
    spot = await _fetch_spot(db, account_id, spot_id)

    if spot.is_assigned:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This spot already has an active assignment. End the current assignment first.",
        )

    assignment = CorporateParkingAssignment(
        account_id=account_id,
        spot_id=spot_id,
        member_id=data.member_id,
        assigned_by_id=assigned_by_id,
        permit_number=data.permit_number,
        start_date=data.start_date,
        end_date=data.end_date,
        is_active=True,
        notes=data.notes,
    )
    db.add(assignment)

    # Mark spot as assigned
    spot.is_assigned = True

    await db.flush()
    await db.refresh(assignment)
    return _to_assignment(assignment)


async def end_assignment(
    db: AsyncSession,
    account_id: int,
    spot_id: uuid.UUID,
    ended_by_id: Optional[int] = None,
) -> AssignmentResponse:
    """End the active assignment for a parking spot.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        spot_id: UUID of the spot whose assignment is being ended.
        ended_by_id: User ID of the admin ending the assignment.

    Returns:
        Updated ``AssignmentResponse`` with is_active=False.

    Raises:
        HTTPException 404: No active assignment found for this spot.
    """
    spot = await _fetch_spot(db, account_id, spot_id)

    stmt = select(CorporateParkingAssignment).where(
        CorporateParkingAssignment.spot_id == spot_id,
        CorporateParkingAssignment.account_id == account_id,
        CorporateParkingAssignment.is_active == True,
    )
    assignment = (await db.execute(stmt)).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active assignment found for this spot.",
        )

    assignment.is_active = False
    assignment.ended_at = datetime.now(tz=timezone.utc)
    assignment.ended_by_id = ended_by_id

    # Clear spot's assigned flag
    spot.is_assigned = False

    await db.flush()
    await db.refresh(assignment)
    return _to_assignment(assignment)


async def get_member_parking(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> List[AssignmentResponse]:
    """Return a member's active parking assignments for the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        member_id: User ID of the employee.

    Returns:
        List of ``AssignmentResponse`` (active assignments only).
    """
    stmt = select(CorporateParkingAssignment).where(
        CorporateParkingAssignment.account_id == account_id,
        CorporateParkingAssignment.member_id == member_id,
        CorporateParkingAssignment.is_active == True,
    )
    result = await db.execute(stmt)
    return [_to_assignment(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Summary / analytics
# ---------------------------------------------------------------------------


async def get_facility_summary(
    db: AsyncSession,
    account_id: int,
    facility_id: uuid.UUID,
) -> FacilitySummaryResponse:
    """Return aggregate statistics for a parking facility.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        facility_id: UUID of the facility.

    Returns:
        ``FacilitySummaryResponse`` with total/active/assigned/available counts
        and a breakdown by spot type.

    Raises:
        HTTPException 404: Facility not found.
    """
    await _fetch_facility(db, account_id, facility_id)

    # Total spots (all)
    total_stmt = select(func.count()).where(
        CorporateParkingSpot.facility_id == facility_id
    )
    total = (await db.execute(total_stmt)).scalar_one()

    # Active spots
    active_stmt = select(func.count()).where(
        CorporateParkingSpot.facility_id == facility_id,
        CorporateParkingSpot.is_active == True,
    )
    active = (await db.execute(active_stmt)).scalar_one()

    # Assigned (active + is_assigned)
    assigned_stmt = select(func.count()).where(
        CorporateParkingSpot.facility_id == facility_id,
        CorporateParkingSpot.is_active == True,
        CorporateParkingSpot.is_assigned == True,
    )
    assigned = (await db.execute(assigned_stmt)).scalar_one()

    # By spot type (active spots only)
    type_stmt = (
        select(CorporateParkingSpot.spot_type, func.count())
        .where(
            CorporateParkingSpot.facility_id == facility_id,
            CorporateParkingSpot.is_active == True,
        )
        .group_by(CorporateParkingSpot.spot_type)
    )
    type_result = await db.execute(type_stmt)
    by_spot_type = {row[0].value: row[1] for row in type_result.all()}

    return FacilitySummaryResponse(
        facility_id=facility_id,
        total_spots=total,
        active_spots=active,
        assigned_spots=assigned,
        available_spots=active - assigned,
        by_spot_type=by_spot_type,
    )


# ---------------------------------------------------------------------------
# Platform-admin
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[FacilityResponse]:
    """Return all parking facilities across all accounts (platform-admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter by corporate account ID.
        skip: Pagination offset.
        limit: Maximum records to return.

    Returns:
        List of ``FacilityResponse``.
    """
    stmt = select(CorporateParkingFacility)
    if account_id is not None:
        stmt = stmt.where(CorporateParkingFacility.account_id == account_id)
    stmt = stmt.order_by(
        CorporateParkingFacility.account_id,
        CorporateParkingFacility.name,
    ).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return [_to_facility(r) for r in result.scalars().all()]
