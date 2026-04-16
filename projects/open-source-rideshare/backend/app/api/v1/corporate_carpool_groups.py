"""Corporate Carpool Groups endpoints.

Groups of corporate employees who share rides together for daily commutes.
Each group can track member pickup points and a sequenced pickup order.

Member endpoints (any active account member):
  GET  /corporate/member/carpool-groups                        — list active groups
  GET  /corporate/member/carpool-groups/my-groups              — groups I belong to
  GET  /corporate/member/carpool-groups/{group_id}             — get group detail

Admin endpoints (account admins only):
  POST   /corporate/admin/carpool-groups                                  — create (201)
  GET    /corporate/admin/carpool-groups                                  — list all
  GET    /corporate/admin/carpool-groups/{group_id}                       — get (200)
  PUT    /corporate/admin/carpool-groups/{group_id}                       — update (200)
  POST   /corporate/admin/carpool-groups/{group_id}/deactivate            — deactivate (200)
  POST   /corporate/admin/carpool-groups/{group_id}/reactivate            — reactivate (200)
  DELETE /corporate/admin/carpool-groups/{group_id}                       — delete (204)
  POST   /corporate/admin/carpool-groups/{group_id}/members               — add member (201)
  DELETE /corporate/admin/carpool-groups/{group_id}/members/{member_id}   — remove member (204)
  GET    /corporate/admin/carpool-groups/{group_id}/members               — list members (200)
  GET    /corporate/admin/carpool-groups/{group_id}/summary               — summary (200)

Platform-admin endpoints:
  GET  /corporate/platform-admin/carpool-groups                              — all groups
  GET  /corporate/platform-admin/carpool-groups/account/{account_id}         — for account
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
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
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_carpool_group import (
    add_member,
    create_group,
    deactivate_group,
    delete_group,
    get_group,
    get_group_summary,
    get_member_carpools,
    list_all_platform,
    list_groups,
    list_members,
    reactivate_group,
    remove_member,
    update_group,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Carpool Groups"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member endpoints: browse groups
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/member/carpool-groups",
    response_model=CarpoolGroupListResponse,
    summary="Member: list active carpool groups in my account",
)
async def member_list_active_groups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active carpool groups for the authenticated user's account.

    Returns 404 if the user is not a corporate account member.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_groups(db, account_id, is_active=True)


@router.get(
    "/corporate/member/carpool-groups/my-groups",
    response_model=CarpoolGroupListResponse,
    summary="Member: list carpool groups I belong to",
)
async def member_list_my_groups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active carpool groups the authenticated user is a member of.

    Returns 404 if the user is not a corporate account member.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_member_carpools(db, account_id, user.id)


@router.get(
    "/corporate/member/carpool-groups/{group_id}",
    response_model=CarpoolGroupResponse,
    summary="Member: get carpool group detail",
)
async def member_get_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single carpool group by ID.

    Returns 404 if not found or the group belongs to a different account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_group(db, group_id, account_id)


# ---------------------------------------------------------------------------
# Admin endpoints: create / list / get
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/admin/carpool-groups",
    response_model=CarpoolGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a carpool group",
)
async def admin_create_group(
    data: CarpoolGroupCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new carpool group for the admin's account.

    Returns 409 if a group with the same name already exists.
    Returns 404 if the user is not a corporate account member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_group(db, account_id, user.id, data)


@router.get(
    "/corporate/admin/carpool-groups",
    response_model=CarpoolGroupListResponse,
    summary="Admin: list carpool groups",
)
async def admin_list_groups(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all carpool groups for the admin's account.

    Optionally filter by ``is_active``.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_groups(db, account_id, is_active=is_active)


@router.get(
    "/corporate/admin/carpool-groups/{group_id}",
    response_model=CarpoolGroupResponse,
    summary="Admin: get carpool group detail",
)
async def admin_get_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single carpool group by ID.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_group(db, group_id, account_id)


# ---------------------------------------------------------------------------
# Admin endpoints: update / deactivate / reactivate / delete
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/admin/carpool-groups/{group_id}",
    response_model=CarpoolGroupResponse,
    summary="Admin: update a carpool group",
)
async def admin_update_group(
    group_id: uuid.UUID,
    data: CarpoolGroupUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a carpool group.

    Returns 404 if not found.  Returns 409 on name collision.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_group(db, group_id, account_id, data)


@router.post(
    "/corporate/admin/carpool-groups/{group_id}/deactivate",
    response_model=CarpoolGroupResponse,
    summary="Admin: deactivate a carpool group",
)
async def admin_deactivate_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a carpool group.

    Returns 404 if not found.  Returns 409 if already inactive.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_group(db, group_id, account_id)


@router.post(
    "/corporate/admin/carpool-groups/{group_id}/reactivate",
    response_model=CarpoolGroupResponse,
    summary="Admin: reactivate a carpool group",
)
async def admin_reactivate_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a carpool group.

    Returns 404 if not found.  Returns 409 if already active.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_group(db, group_id, account_id)


@router.delete(
    "/corporate/admin/carpool-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: delete a carpool group",
)
async def admin_delete_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a carpool group (must be inactive first).

    Returns 404 if not found.  Returns 409 if still active.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_group(db, group_id, account_id)


# ---------------------------------------------------------------------------
# Admin endpoints: members
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/admin/carpool-groups/{group_id}/members",
    response_model=CarpoolMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a member to a carpool group",
)
async def admin_add_member(
    group_id: uuid.UUID,
    data: CarpoolMemberCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enroll an employee in a carpool group.

    Returns 404 if the group is not found.
    Returns 409 if the employee is already a member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await add_member(db, group_id, account_id, data, added_by_id=user.id)


@router.delete(
    "/corporate/admin/carpool-groups/{group_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: remove a member from a carpool group",
)
async def admin_remove_member(
    group_id: uuid.UUID,
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an employee from a carpool group.

    Returns 404 if the membership record is not found.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await remove_member(db, group_id, account_id, member_id)


@router.get(
    "/corporate/admin/carpool-groups/{group_id}/members",
    response_model=CarpoolMemberListResponse,
    summary="Admin: list members of a carpool group",
)
async def admin_list_members(
    group_id: uuid.UUID,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all members of a carpool group.

    Ordered by pickup_sequence (NULLS LAST) then joined_at.
    Optionally filter by ``is_active``.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_members(db, group_id, account_id, is_active=is_active)


@router.get(
    "/corporate/admin/carpool-groups/{group_id}/summary",
    response_model=CarpoolGroupSummary,
    summary="Admin: get carpool group summary with member counts",
)
async def admin_get_group_summary(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a summary of a carpool group including total and active member counts.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_group_summary(db, group_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/platform-admin/carpool-groups",
    response_model=CarpoolGroupListResponse,
    summary="Platform admin: list all carpool groups",
)
async def platform_list_all(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all carpool groups across all accounts.

    Optionally filter by ``account_id``.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


@router.get(
    "/corporate/platform-admin/carpool-groups/account/{account_id}",
    response_model=CarpoolGroupListResponse,
    summary="Platform admin: list all carpool groups for a specific account",
)
async def platform_list_for_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all carpool groups for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)
