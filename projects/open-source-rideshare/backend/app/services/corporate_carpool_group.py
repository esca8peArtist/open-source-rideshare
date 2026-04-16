"""Service layer for Corporate Carpool Groups.

Corporate employees who share rides together for daily commutes can be
organised into carpool groups.  Each group tracks its members with optional
personal pickup points and a sequencing order.

Public surface
--------------
create_group(db, account_id, created_by_id, data) -> CarpoolGroupResponse
get_group(db, group_id, account_id) -> CarpoolGroupResponse
list_groups(db, account_id, *, is_active) -> CarpoolGroupListResponse
update_group(db, group_id, account_id, data) -> CarpoolGroupResponse
deactivate_group(db, group_id, account_id) -> CarpoolGroupResponse
reactivate_group(db, group_id, account_id) -> CarpoolGroupResponse
delete_group(db, group_id, account_id) -> None
add_member(db, group_id, account_id, data, added_by_id) -> CarpoolMemberResponse
remove_member(db, group_id, account_id, member_id) -> None
list_members(db, group_id, account_id, *, is_active) -> CarpoolMemberListResponse
get_member_carpools(db, account_id, member_id) -> CarpoolGroupListResponse
get_group_summary(db, group_id, account_id) -> CarpoolGroupSummary
list_all_platform(db, *, account_id) -> CarpoolGroupListResponse
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_carpool_group import (
    CorporateCarpoolGroup,
    CorporateCarpoolMember,
)
from app.schemas.corporate_carpool_group import (
    CarpoolGroupCreate,
    CarpoolGroupListResponse,
    CarpoolGroupResponse,
    CarpoolGroupSummary,
    CarpoolGroupUpdate,
    CarpoolMemberCreate,
    CarpoolMemberListResponse,
    CarpoolMemberResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _group_to_response(group: CorporateCarpoolGroup) -> CarpoolGroupResponse:
    """Convert a CorporateCarpoolGroup ORM instance to a response schema."""
    return CarpoolGroupResponse(
        id=group.id,
        account_id=group.account_id,
        name=group.name,
        description=group.description,
        max_members=group.max_members,
        home_base_address=group.home_base_address,
        home_base_lat=(
            float(group.home_base_lat) if group.home_base_lat is not None else None
        ),
        home_base_lng=(
            float(group.home_base_lng) if group.home_base_lng is not None else None
        ),
        destination_address=group.destination_address,
        destination_lat=(
            float(group.destination_lat) if group.destination_lat is not None else None
        ),
        destination_lng=(
            float(group.destination_lng) if group.destination_lng is not None else None
        ),
        departure_time=group.departure_time,
        days_of_week=group.days_of_week,
        vehicle_type=group.vehicle_type,
        cost_center_id=group.cost_center_id,
        trip_purpose_id=group.trip_purpose_id,
        is_active=group.is_active,
        created_by_id=group.created_by_id,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _member_to_response(member: CorporateCarpoolMember) -> CarpoolMemberResponse:
    """Convert a CorporateCarpoolMember ORM instance to a response schema."""
    return CarpoolMemberResponse(
        id=member.id,
        carpool_group_id=member.carpool_group_id,
        account_id=member.account_id,
        member_id=member.member_id,
        pickup_address=member.pickup_address,
        pickup_lat=(
            float(member.pickup_lat) if member.pickup_lat is not None else None
        ),
        pickup_lng=(
            float(member.pickup_lng) if member.pickup_lng is not None else None
        ),
        pickup_sequence=member.pickup_sequence,
        is_active=member.is_active,
        added_by_id=member.added_by_id,
        notes=member.notes,
        joined_at=member.joined_at,
    )


async def _get_group_by_id(
    db: AsyncSession, group_id: uuid.UUID
) -> CorporateCarpoolGroup | None:
    """Return the carpool group by primary key, or None."""
    result = await db.execute(
        select(CorporateCarpoolGroup).where(CorporateCarpoolGroup.id == group_id)
    )
    return result.scalar_one_or_none()


async def _get_group_or_404(
    db: AsyncSession, group_id: uuid.UUID, account_id: int
) -> CorporateCarpoolGroup:
    """Return the carpool group or raise HTTP 404.

    Also verifies the group belongs to the given account.
    """
    result = await db.execute(
        select(CorporateCarpoolGroup).where(
            CorporateCarpoolGroup.id == group_id,
            CorporateCarpoolGroup.account_id == account_id,
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Carpool group not found.",
        )
    return group


# ---------------------------------------------------------------------------
# Public service functions — groups
# ---------------------------------------------------------------------------


async def create_group(
    db: AsyncSession,
    account_id: int,
    created_by_id: Optional[int],
    data: CarpoolGroupCreate,
) -> CarpoolGroupResponse:
    """Create a new carpool group within the given account.

    Raises HTTP 409 if a group with the same name (case-insensitive) already
    exists in this account.
    """
    existing = await db.execute(
        select(CorporateCarpoolGroup).where(
            CorporateCarpoolGroup.account_id == account_id,
            func.lower(CorporateCarpoolGroup.name) == data.name.lower(),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A carpool group with this name already exists in the account.",
        )

    group = CorporateCarpoolGroup(
        account_id=account_id,
        created_by_id=created_by_id,
        name=data.name,
        description=data.description,
        max_members=data.max_members,
        home_base_address=data.home_base_address,
        home_base_lat=data.home_base_lat,
        home_base_lng=data.home_base_lng,
        destination_address=data.destination_address,
        destination_lat=data.destination_lat,
        destination_lng=data.destination_lng,
        departure_time=data.departure_time,
        days_of_week=data.days_of_week,
        vehicle_type=data.vehicle_type,
        cost_center_id=data.cost_center_id,
        trip_purpose_id=data.trip_purpose_id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _group_to_response(group)


async def get_group(
    db: AsyncSession, group_id: uuid.UUID, account_id: int
) -> CarpoolGroupResponse:
    """Return a carpool group by ID.

    Raises HTTP 404 if not found or the group belongs to a different account.
    """
    group = await _get_group_or_404(db, group_id, account_id)
    return _group_to_response(group)


async def list_groups(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> CarpoolGroupListResponse:
    """List all carpool groups for an account, ordered by name.

    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    stmt = select(CorporateCarpoolGroup).where(
        CorporateCarpoolGroup.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateCarpoolGroup.is_active == is_active)
    stmt = stmt.order_by(CorporateCarpoolGroup.name)

    result = await db.execute(stmt)
    groups = result.scalars().all()
    return CarpoolGroupListResponse(
        items=[_group_to_response(g) for g in groups],
        total=len(groups),
    )


async def update_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    account_id: int,
    data: CarpoolGroupUpdate,
) -> CarpoolGroupResponse:
    """Partially update a carpool group.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the new name collides with another group in the account.
    """
    group = await _get_group_or_404(db, group_id, account_id)

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        new_name = update_data["name"]
        collision = await db.execute(
            select(CorporateCarpoolGroup).where(
                CorporateCarpoolGroup.account_id == account_id,
                func.lower(CorporateCarpoolGroup.name) == new_name.lower(),
                CorporateCarpoolGroup.id != group_id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A carpool group with this name already exists in the account.",
            )

    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    return _group_to_response(group)


async def deactivate_group(
    db: AsyncSession, group_id: uuid.UUID, account_id: int
) -> CarpoolGroupResponse:
    """Deactivate a carpool group.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the group is already inactive.
    """
    group = await _get_group_or_404(db, group_id, account_id)
    if not group.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Carpool group is already inactive",
        )
    group.is_active = False
    await db.commit()
    await db.refresh(group)
    return _group_to_response(group)


async def reactivate_group(
    db: AsyncSession, group_id: uuid.UUID, account_id: int
) -> CarpoolGroupResponse:
    """Reactivate a carpool group.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the group is already active.
    """
    group = await _get_group_or_404(db, group_id, account_id)
    if group.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Carpool group is already active",
        )
    group.is_active = True
    await db.commit()
    await db.refresh(group)
    return _group_to_response(group)


async def delete_group(
    db: AsyncSession, group_id: uuid.UUID, account_id: int
) -> None:
    """Hard-delete a carpool group.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the group is still active (deactivate first).
    """
    group = await _get_group_or_404(db, group_id, account_id)
    if group.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active carpool group — deactivate it first",
        )
    await db.delete(group)
    await db.commit()


# ---------------------------------------------------------------------------
# Public service functions — members
# ---------------------------------------------------------------------------


async def add_member(
    db: AsyncSession,
    group_id: uuid.UUID,
    account_id: int,
    data: CarpoolMemberCreate,
    added_by_id: Optional[int] = None,
) -> CarpoolMemberResponse:
    """Enroll a user in a carpool group.

    Raises HTTP 404 if the group is not found.
    Raises HTTP 409 if the user is already a member of this group.
    """
    group = await _get_group_or_404(db, group_id, account_id)

    existing = await db.execute(
        select(CorporateCarpoolMember).where(
            CorporateCarpoolMember.carpool_group_id == group_id,
            CorporateCarpoolMember.member_id == data.member_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member is already in this carpool group",
        )

    member = CorporateCarpoolMember(
        carpool_group_id=group.id,
        account_id=group.account_id,
        member_id=data.member_id,
        pickup_address=data.pickup_address,
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        pickup_sequence=data.pickup_sequence,
        added_by_id=added_by_id,
        notes=data.notes,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return _member_to_response(member)


async def remove_member(
    db: AsyncSession,
    group_id: uuid.UUID,
    account_id: int,
    member_id: int,
) -> None:
    """Remove a member from a carpool group.

    Raises HTTP 404 if the membership record is not found.
    """
    result = await db.execute(
        select(CorporateCarpoolMember).where(
            CorporateCarpoolMember.carpool_group_id == group_id,
            CorporateCarpoolMember.account_id == account_id,
            CorporateCarpoolMember.member_id == member_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this carpool group.",
        )
    await db.delete(membership)
    await db.commit()


async def list_members(
    db: AsyncSession,
    group_id: uuid.UUID,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> CarpoolMemberListResponse:
    """List members of a carpool group, ordered by pickup_sequence then joined_at.

    Raises HTTP 404 if the group is not found.
    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    await _get_group_or_404(db, group_id, account_id)

    stmt = select(CorporateCarpoolMember).where(
        CorporateCarpoolMember.carpool_group_id == group_id,
        CorporateCarpoolMember.account_id == account_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateCarpoolMember.is_active == is_active)
    stmt = stmt.order_by(
        CorporateCarpoolMember.pickup_sequence.nulls_last(),
        CorporateCarpoolMember.joined_at,
    )

    result = await db.execute(stmt)
    members = result.scalars().all()
    return CarpoolMemberListResponse(
        items=[_member_to_response(m) for m in members],
        total=len(members),
    )


async def get_member_carpools(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> CarpoolGroupListResponse:
    """Return all active carpool groups the member belongs to, ordered by name."""
    stmt = (
        select(CorporateCarpoolGroup)
        .join(
            CorporateCarpoolMember,
            CorporateCarpoolMember.carpool_group_id == CorporateCarpoolGroup.id,
        )
        .where(
            CorporateCarpoolMember.member_id == member_id,
            CorporateCarpoolGroup.account_id == account_id,
            CorporateCarpoolGroup.is_active == True,  # noqa: E712
        )
        .order_by(CorporateCarpoolGroup.name)
    )
    result = await db.execute(stmt)
    groups = result.scalars().all()
    return CarpoolGroupListResponse(
        items=[_group_to_response(g) for g in groups],
        total=len(groups),
    )


async def get_group_summary(
    db: AsyncSession,
    group_id: uuid.UUID,
    account_id: int,
) -> CarpoolGroupSummary:
    """Return a lightweight summary of a carpool group with member counts.

    Raises HTTP 404 if not found.
    """
    group = await _get_group_or_404(db, group_id, account_id)

    total_result = await db.execute(
        select(func.count(CorporateCarpoolMember.id)).where(
            CorporateCarpoolMember.carpool_group_id == group_id,
        )
    )
    total_members = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count(CorporateCarpoolMember.id)).where(
            CorporateCarpoolMember.carpool_group_id == group_id,
            CorporateCarpoolMember.is_active == True,  # noqa: E712
        )
    )
    active_members = active_result.scalar() or 0

    return CarpoolGroupSummary(
        group_id=group.id,
        name=group.name,
        total_members=total_members,
        active_members=active_members,
        has_destination=group.destination_address is not None,
        has_departure_time=group.departure_time is not None,
        days_of_week=group.days_of_week,
    )


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
) -> CarpoolGroupListResponse:
    """Platform-admin: list all carpool groups, optionally filtered by account.

    When ``account_id`` is provided, only groups for that account are returned.
    """
    stmt = select(CorporateCarpoolGroup)
    if account_id is not None:
        stmt = stmt.where(CorporateCarpoolGroup.account_id == account_id)
    stmt = stmt.order_by(CorporateCarpoolGroup.account_id, CorporateCarpoolGroup.name)

    result = await db.execute(stmt)
    groups = result.scalars().all()
    return CarpoolGroupListResponse(
        items=[_group_to_response(g) for g in groups],
        total=len(groups),
    )
