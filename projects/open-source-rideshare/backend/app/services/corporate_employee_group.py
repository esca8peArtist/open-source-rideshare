"""Service functions for Corporate Employee Groups.

Enterprise admins create named groups of employees that cross org-chart
boundaries.  Groups are more flexible than departments — one employee can
belong to many groups and groups do not need to correspond to org structure.

Public API
----------
create_group           — create a group; 409 if name already taken within account
get_group              — fetch one group; 404 if not found or wrong account
list_groups            — paginated list, optionally filtering to active only
update_group           — update name/description/color; 409 on name conflict
deactivate_group       — soft-delete (is_active=False); 404 if not found
delete_group           — hard delete; 404 if not found
add_member_to_group    — add membership; 404 if group/member unknown; 409 if dupe
remove_member_from_group — remove membership; 404 if not found
list_group_members     — paginated memberships for a group
get_member_groups      — all groups a member belongs to
get_group_stats        — {group_id, name, member_count, active_members, created_at}
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember
from app.models.corporate_employee_group import (
    CorporateEmployeeGroup,
    CorporateGroupMembership,
)
from app.schemas.corporate_employee_group import (
    GroupCreate,
    GroupStatsResponse,
    GroupUpdate,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_group_by_id(
    db: AsyncSession, group_id: int, account_id: int
) -> Optional[CorporateEmployeeGroup]:
    """Return the group row matching *group_id* within *account_id*, or None."""
    result = await db.execute(
        select(CorporateEmployeeGroup).where(
            CorporateEmployeeGroup.id == group_id,
            CorporateEmployeeGroup.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_group_by_name(
    db: AsyncSession, account_id: int, name: str
) -> Optional[CorporateEmployeeGroup]:
    """Return the group row matching *name* within *account_id*, or None."""
    result = await db.execute(
        select(CorporateEmployeeGroup).where(
            CorporateEmployeeGroup.account_id == account_id,
            CorporateEmployeeGroup.name == name,
        )
    )
    return result.scalar_one_or_none()


async def _require_group(
    db: AsyncSession, group_id: int, account_id: int
) -> CorporateEmployeeGroup:
    """Return the group or raise HTTP 404."""
    group = await _get_group_by_id(db, group_id, account_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee group not found.",
        )
    return group


async def _get_membership(
    db: AsyncSession, group_id: int, member_id: int
) -> Optional[CorporateGroupMembership]:
    """Return the membership row or None."""
    result = await db.execute(
        select(CorporateGroupMembership).where(
            CorporateGroupMembership.group_id == group_id,
            CorporateGroupMembership.member_id == member_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def create_group(
    db: AsyncSession,
    account_id: int,
    data: GroupCreate,
    created_by_id: int,
) -> CorporateEmployeeGroup:
    """Create a new employee group within *account_id*.

    Raises HTTP 409 if a group with the same name already exists for the
    account (names are unique per account, case-sensitive).
    """
    existing = await _get_group_by_name(db, account_id, data.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A group with this name already exists for the account.",
        )

    group = CorporateEmployeeGroup(
        account_id=account_id,
        name=data.name,
        description=data.description,
        color=data.color,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(group)
    await db.flush()
    return group


async def get_group(
    db: AsyncSession, group_id: int, account_id: int
) -> CorporateEmployeeGroup:
    """Return the group identified by *group_id* within *account_id*.

    Raises HTTP 404 if not found or if the group belongs to a different account.
    """
    return await _require_group(db, group_id, account_id)


async def list_groups(
    db: AsyncSession,
    account_id: int,
    skip: int = 0,
    limit: int = 50,
    active_only: bool = True,
) -> list[CorporateEmployeeGroup]:
    """Return a paginated list of employee groups for *account_id*.

    When *active_only* is True (the default) only groups with is_active=True
    are returned.  Pass False to include deactivated groups in audit views.
    """
    query = (
        select(CorporateEmployeeGroup)
        .where(CorporateEmployeeGroup.account_id == account_id)
        .order_by(CorporateEmployeeGroup.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if active_only:
        query = query.where(CorporateEmployeeGroup.is_active.is_(True))

    result = await db.execute(query)
    return list(result.scalars().all())


async def update_group(
    db: AsyncSession,
    group_id: int,
    account_id: int,
    data: GroupUpdate,
) -> CorporateEmployeeGroup:
    """Update fields on an existing employee group.

    Raises HTTP 404 if the group does not exist.
    Raises HTTP 409 if renaming would collide with another group's name.
    """
    group = await _require_group(db, group_id, account_id)

    if data.name is not None and data.name != group.name:
        conflict = await _get_group_by_name(db, account_id, data.name)
        if conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A group with this name already exists for the account.",
            )
        group.name = data.name

    if data.description is not None:
        group.description = data.description
    if data.color is not None:
        group.color = data.color
    if data.is_active is not None:
        group.is_active = data.is_active

    await db.flush()
    return group


async def deactivate_group(
    db: AsyncSession, group_id: int, account_id: int
) -> CorporateEmployeeGroup:
    """Soft-delete a group by setting is_active=False.

    Raises HTTP 404 if the group does not exist.
    """
    group = await _require_group(db, group_id, account_id)
    group.is_active = False
    await db.flush()
    return group


async def delete_group(
    db: AsyncSession, group_id: int, account_id: int
) -> None:
    """Hard-delete a group and all its memberships (via CASCADE).

    Raises HTTP 404 if the group does not exist.
    """
    group = await _require_group(db, group_id, account_id)
    await db.delete(group)
    await db.flush()


async def add_member_to_group(
    db: AsyncSession,
    group_id: int,
    account_id: int,
    member_id: int,
    added_by_id: int,
) -> CorporateGroupMembership:
    """Add *member_id* to the employee group *group_id*.

    Raises HTTP 404 if the group is not found within *account_id*.
    Raises HTTP 404 if the member is not found within *account_id*.
    Raises HTTP 409 if the member is already in the group.
    """
    # Verify the group exists within this account.
    await _require_group(db, group_id, account_id)

    # Verify the member belongs to this account.
    member_result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.id == member_id,
            BusinessAccountMember.account_id == account_id,
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this corporate account.",
        )

    # Check for duplicate membership.
    existing = await _get_membership(db, group_id, member_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This member is already in the group.",
        )

    membership = CorporateGroupMembership(
        group_id=group_id,
        member_id=member_id,
        added_by_id=added_by_id,
    )
    db.add(membership)
    await db.flush()
    return membership


async def remove_member_from_group(
    db: AsyncSession,
    group_id: int,
    account_id: int,
    member_id: int,
) -> None:
    """Remove the membership of *member_id* from group *group_id*.

    Raises HTTP 404 if the group does not exist or the membership does not exist.
    """
    await _require_group(db, group_id, account_id)

    membership = await _get_membership(db, group_id, member_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found.",
        )
    await db.delete(membership)
    await db.flush()


async def list_group_members(
    db: AsyncSession,
    group_id: int,
    account_id: int,
    skip: int = 0,
    limit: int = 50,
) -> list[CorporateGroupMembership]:
    """Return paginated memberships for a group.

    Raises HTTP 404 if the group does not exist.
    """
    await _require_group(db, group_id, account_id)

    result = await db.execute(
        select(CorporateGroupMembership)
        .where(CorporateGroupMembership.group_id == group_id)
        .order_by(CorporateGroupMembership.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_member_groups(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> list[CorporateEmployeeGroup]:
    """Return all active groups that *member_id* belongs to within *account_id*.

    Does not raise 404 if the member has no groups — returns an empty list.
    """
    result = await db.execute(
        select(CorporateEmployeeGroup)
        .join(
            CorporateGroupMembership,
            CorporateGroupMembership.group_id == CorporateEmployeeGroup.id,
        )
        .where(
            CorporateEmployeeGroup.account_id == account_id,
            CorporateGroupMembership.member_id == member_id,
            CorporateEmployeeGroup.is_active.is_(True),
        )
        .order_by(CorporateEmployeeGroup.name.asc())
    )
    return list(result.scalars().all())


async def get_group_stats(
    db: AsyncSession,
    group_id: int,
    account_id: int,
) -> GroupStatsResponse:
    """Return aggregate statistics for a single group.

    Raises HTTP 404 if the group does not exist.
    """
    group = await _require_group(db, group_id, account_id)

    # Total memberships for this group.
    count_result = await db.execute(
        select(func.count(CorporateGroupMembership.id)).where(
            CorporateGroupMembership.group_id == group_id,
        )
    )
    member_count: int = count_result.scalar_one() or 0

    # Active members (those whose account membership is still active).
    active_result = await db.execute(
        select(func.count(CorporateGroupMembership.id))
        .join(
            BusinessAccountMember,
            BusinessAccountMember.id == CorporateGroupMembership.member_id,
        )
        .where(
            CorporateGroupMembership.group_id == group_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    active_members: int = active_result.scalar_one() or 0

    return GroupStatsResponse(
        group_id=group.id,
        name=group.name,
        member_count=member_count,
        active_members=active_members,
        created_at=group.created_at,
    )
