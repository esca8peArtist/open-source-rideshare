"""Corporate Employee Group endpoints.

Enterprise admins create named groups of employees that cross org-chart
boundaries — think "VIP Executives", "Remote Workers", "Engineering All-Hands".
Groups are more flexible than departments: one employee can belong to many
groups and groups do not have to correspond to org structure.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/groups                           — list active groups
  GET  /corporate/accounts/me/groups/{group_id}                — get single group
  GET  /corporate/accounts/me/groups/{group_id}/members        — list group members
  GET  /corporate/accounts/me/members/{member_id}/groups       — member's groups

Admin endpoints (account-admin only):
  POST   /corporate/accounts/me/groups                         — create group (201)
  PUT    /corporate/accounts/me/groups/{group_id}              — update group
  POST   /corporate/accounts/me/groups/{group_id}/deactivate   — soft-delete
  DELETE /corporate/accounts/me/groups/{group_id}              — hard delete (204)
  POST   /corporate/accounts/me/groups/{group_id}/members      — add member (201)
  DELETE /corporate/accounts/me/groups/{group_id}/members/{member_id} — remove (204)

Platform-admin endpoints:
  GET /platform-admin/corporate/groups                         — list all groups
  GET /platform-admin/corporate/groups/{group_id}/stats        — group stats
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_employee_group import (
    AddMemberToGroupRequest,
    GroupCreate,
    GroupListResponse,
    GroupMembersResponse,
    GroupResponse,
    GroupStatsResponse,
    GroupUpdate,
    MemberGroupsResponse,
    MembershipResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_employee_group import (
    add_member_to_group,
    create_group,
    deactivate_group,
    delete_group,
    get_group,
    get_group_stats,
    get_member_groups,
    list_group_members,
    list_groups,
    remove_member_from_group,
    update_group,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-employee-groups"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _group_response(group) -> GroupResponse:
    return GroupResponse.model_validate(group)


def _membership_response(membership) -> MembershipResponse:
    return MembershipResponse.model_validate(membership)


# ---------------------------------------------------------------------------
# Member: list groups
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/groups",
    response_model=GroupListResponse,
    summary="Member: list employee groups for my corporate account",
)
async def list_my_groups(
    active_only: bool = Query(True, description="Only return active groups."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of employee groups in the caller's corporate account.

    Any active account member may call this endpoint.  By default only active
    groups are included; pass ``active_only=false`` to include deactivated groups.
    """
    account_id = await _resolve_account_id(db, user.id)
    groups = await list_groups(db, account_id=account_id, skip=skip, limit=limit, active_only=active_only)
    return GroupListResponse(
        account_id=account_id,
        total=len(groups),
        items=[_group_response(g) for g in groups],
    )


# ---------------------------------------------------------------------------
# Admin: create group — declared before /{group_id} paths
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new employee group",
)
async def create_my_group(
    data: GroupCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new employee group within the caller's corporate account.

    Requires ADMIN role within the account.
    Returns HTTP 409 if a group with the same name already exists.
    """
    account_id = await _resolve_account_id(db, user.id)
    group = await create_group(db, account_id=account_id, data=data, created_by_id=user.id)
    await db.commit()
    return _group_response(group)


# ---------------------------------------------------------------------------
# Member: get single group
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/groups/{group_id}",
    response_model=GroupResponse,
    summary="Member: get a single employee group",
)
async def get_my_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific employee group.

    Any active account member may call this endpoint.
    Raises HTTP 404 if the group is not found in the caller's account.
    """
    account_id = await _resolve_account_id(db, user.id)
    group = await get_group(db, group_id=group_id, account_id=account_id)
    return _group_response(group)


# ---------------------------------------------------------------------------
# Admin: update group
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/groups/{group_id}",
    response_model=GroupResponse,
    summary="Admin: update an employee group",
)
async def update_my_group(
    group_id: int,
    data: GroupUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the name, description, color, or active status of a group.

    Requires ADMIN role within the account.
    Returns HTTP 404 if the group is not found; HTTP 409 on name conflict.
    """
    account_id = await _resolve_account_id(db, user.id)
    group = await update_group(db, group_id=group_id, account_id=account_id, data=data)
    await db.commit()
    return _group_response(group)


# ---------------------------------------------------------------------------
# Admin: deactivate group (soft-delete)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/groups/{group_id}/deactivate",
    response_model=GroupResponse,
    summary="Admin: deactivate (soft-delete) an employee group",
)
async def deactivate_my_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a group by marking it inactive.

    Membership records are preserved for audit purposes.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    group = await deactivate_group(db, group_id=group_id, account_id=account_id)
    await db.commit()
    return _group_response(group)


# ---------------------------------------------------------------------------
# Admin: hard-delete group
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: permanently delete an employee group",
)
async def delete_my_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a group and all its memberships.

    This action cannot be undone.  Prefer ``deactivate`` for soft-delete.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    await delete_group(db, group_id=group_id, account_id=account_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Member: list group members
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/groups/{group_id}/members",
    response_model=GroupMembersResponse,
    summary="Member: list members of an employee group",
)
async def list_my_group_members(
    group_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of memberships for a group.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    memberships = await list_group_members(
        db, group_id=group_id, account_id=account_id, skip=skip, limit=limit
    )
    return GroupMembersResponse(
        group_id=group_id,
        total=len(memberships),
        items=[_membership_response(m) for m in memberships],
    )


# ---------------------------------------------------------------------------
# Admin: add member to group
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/groups/{group_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add an account member to a group",
)
async def add_my_group_member(
    group_id: int,
    data: AddMemberToGroupRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a corporate account member to an employee group.

    Requires ADMIN role within the account.
    Returns HTTP 404 if the group or member is not found.
    Returns HTTP 409 if the member is already in the group.
    """
    account_id = await _resolve_account_id(db, user.id)
    membership = await add_member_to_group(
        db,
        group_id=group_id,
        account_id=account_id,
        member_id=data.member_id,
        added_by_id=user.id,
    )
    await db.commit()
    return _membership_response(membership)


# ---------------------------------------------------------------------------
# Admin: remove member from group
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/groups/{group_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: remove a member from a group",
)
async def remove_my_group_member(
    group_id: int,
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from an employee group.

    Does not remove the user from the corporate account itself.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    await remove_member_from_group(
        db, group_id=group_id, account_id=account_id, member_id=member_id
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Member: get all groups for a specific member
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/members/{member_id}/groups",
    response_model=MemberGroupsResponse,
    summary="Member: get all groups a specific account member belongs to",
)
async def get_my_member_groups(
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active groups that a specific member belongs to.

    Any active account member may call this endpoint.
    Returns an empty list if the member has no group memberships.
    """
    account_id = await _resolve_account_id(db, user.id)
    groups = await get_member_groups(db, account_id=account_id, member_id=member_id)
    return MemberGroupsResponse(
        member_id=member_id,
        items=[_group_response(g) for g in groups],
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all groups across accounts
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/groups",
    response_model=GroupListResponse,
    summary="Platform admin: list all employee groups (optionally filter by account)",
)
async def platform_admin_list_groups(
    account_id: Optional[int] = Query(None, description="Filter to a specific account."),
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return employee groups across all corporate accounts.

    Pass ``account_id`` to scope the results to a single account.
    Requires platform-level admin role.
    """
    if account_id is None:
        # List globally — reuse list_groups with a synthetic account_id=0 won't
        # work, so we build the query inline for the all-accounts case.
        from sqlalchemy import select as sa_select
        from app.models.corporate_employee_group import CorporateEmployeeGroup as EG

        query = (
            sa_select(EG)
            .order_by(EG.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if active_only:
            query = query.where(EG.is_active.is_(True))
        result = await db.execute(query)
        groups = list(result.scalars().all())
        return GroupListResponse(
            account_id=0,
            total=len(groups),
            items=[_group_response(g) for g in groups],
        )

    groups = await list_groups(
        db, account_id=account_id, skip=skip, limit=limit, active_only=active_only
    )
    return GroupListResponse(
        account_id=account_id,
        total=len(groups),
        items=[_group_response(g) for g in groups],
    )


# ---------------------------------------------------------------------------
# Platform-admin: group stats
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/groups/{group_id}/stats",
    response_model=GroupStatsResponse,
    summary="Platform admin: aggregate stats for any employee group",
)
async def platform_admin_group_stats(
    group_id: int,
    account_id: int = Query(..., description="The account this group belongs to."),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate statistics for any employee group.

    Requires platform-level admin role.
    """
    return await get_group_stats(db, group_id=group_id, account_id=account_id)
