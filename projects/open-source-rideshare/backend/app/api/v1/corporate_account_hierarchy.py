"""Corporate Account Hierarchy endpoints.

Enterprise accounts can define parent/child relationships with other corporate
accounts.  Platform admins manage these relationships; account admins can view
their own position in the hierarchy.

Platform-admin endpoints (require_admin):
  POST   /platform-admin/corporate/account-hierarchy                                    — create link (201)
  GET    /platform-admin/corporate/account-hierarchy/all                                — list all links
  GET    /platform-admin/corporate/account-hierarchy/{link_id}                          — get link
  PUT    /platform-admin/corporate/account-hierarchy/{link_id}                          — update link
  DELETE /platform-admin/corporate/account-hierarchy/{link_id}                          — delete link (204)
  GET    /platform-admin/corporate/account-hierarchy/account/{account_id}/tree          — hierarchy tree
  GET    /platform-admin/corporate/account-hierarchy/account/{account_id}/children      — children
  GET    /platform-admin/corporate/account-hierarchy/account/{account_id}/parents       — parents
  GET    /platform-admin/corporate/account-hierarchy/account/{account_id}/consolidated  — summary

Account-admin endpoints:
  GET    /corporate/admin/hierarchy/children    — children of my account
  GET    /corporate/admin/hierarchy/parents     — parents of my account
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_account_hierarchy import (
    ConsolidatedSummaryResponse,
    HierarchyLinkCreate,
    HierarchyLinkListResponse,
    HierarchyLinkResponse,
    HierarchyLinkUpdate,
    HierarchyTreeResponse,
)
from app.services.corporate_account_hierarchy import (
    create_hierarchy_link,
    get_account_hierarchy_tree,
    get_consolidated_summary,
    get_hierarchy_link,
    list_all_platform,
    list_children,
    list_parents,
    remove_hierarchy_link,
    update_hierarchy_link,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-hierarchy"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    from fastapi import HTTPException

    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Platform-admin: create link
# ---------------------------------------------------------------------------


@router.post(
    "/platform-admin/corporate/account-hierarchy",
    response_model=HierarchyLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Platform admin: create a corporate account hierarchy link",
)
async def platform_create_link(
    data: HierarchyLinkCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a parent→child relationship between two corporate accounts.

    Returns 422 if parent == child or if the link would create a cycle.
    Returns 409 if the pair already has a link.
    Platform admin only.
    """
    return await create_hierarchy_link(db, data, created_by_id=_admin.id)


# ---------------------------------------------------------------------------
# Platform-admin: list all
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/account-hierarchy/all",
    response_model=HierarchyLinkListResponse,
    summary="Platform admin: list all corporate account hierarchy links",
)
async def platform_list_all(
    account_id: int | None = Query(
        None, description="Filter by parent or child account ID"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all hierarchy links across all corporate accounts.

    Optionally filter by ``account_id`` (matches either parent or child).
    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: account-scoped tree / children / parents / consolidated
# (These must be declared BEFORE the {link_id} routes to avoid route shadowing)
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/account-hierarchy/account/{account_id}/tree",
    response_model=HierarchyTreeResponse,
    summary="Platform admin: get the full hierarchy tree for an account",
)
async def platform_get_tree(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the full hierarchy tree rooted at ``account_id``.

    Follows active child links only, capped at depth 10.
    Platform admin only.
    """
    return await get_account_hierarchy_tree(db, account_id)


@router.get(
    "/platform-admin/corporate/account-hierarchy/account/{account_id}/children",
    response_model=HierarchyLinkListResponse,
    summary="Platform admin: list direct children of an account",
)
async def platform_list_children(
    account_id: int,
    is_active: bool | None = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all direct child links for ``account_id``.

    Optionally filter by ``is_active``.  Platform admin only.
    """
    return await list_children(db, account_id, is_active=is_active)


@router.get(
    "/platform-admin/corporate/account-hierarchy/account/{account_id}/parents",
    response_model=HierarchyLinkListResponse,
    summary="Platform admin: list direct parents of an account",
)
async def platform_list_parents(
    account_id: int,
    is_active: bool | None = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all direct parent links for ``account_id``.

    Optionally filter by ``is_active``.  Platform admin only.
    """
    return await list_parents(db, account_id, is_active=is_active)


@router.get(
    "/platform-admin/corporate/account-hierarchy/account/{account_id}/consolidated",
    response_model=ConsolidatedSummaryResponse,
    summary="Platform admin: get consolidated hierarchy summary for an account",
)
async def platform_consolidated_summary(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate counts for the hierarchy rooted at ``account_id``.

    Includes total accounts, direct children, all descendants, and the full
    list of account IDs.  Platform admin only.
    """
    return await get_consolidated_summary(db, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: get / update / delete a single link by ID
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/account-hierarchy/{link_id}",
    response_model=HierarchyLinkResponse,
    summary="Platform admin: get a corporate account hierarchy link",
)
async def platform_get_link(
    link_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a single hierarchy link by ID.

    Returns 404 if not found.  Platform admin only.
    """
    return await get_hierarchy_link(db, link_id)


@router.put(
    "/platform-admin/corporate/account-hierarchy/{link_id}",
    response_model=HierarchyLinkResponse,
    summary="Platform admin: update a corporate account hierarchy link",
)
async def platform_update_link(
    link_id: uuid.UUID,
    data: HierarchyLinkUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a hierarchy link.

    Returns 404 if not found.  Platform admin only.
    """
    return await update_hierarchy_link(db, link_id, data)


@router.delete(
    "/platform-admin/corporate/account-hierarchy/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Platform admin: delete a corporate account hierarchy link",
)
async def platform_delete_link(
    link_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a hierarchy link.

    Returns 404 if not found.  Platform admin only.
    """
    await remove_hierarchy_link(db, link_id)


# ---------------------------------------------------------------------------
# Account-admin: view own hierarchy position
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/admin/hierarchy/children",
    response_model=HierarchyLinkListResponse,
    summary="Account admin: list child accounts in my hierarchy",
)
async def admin_list_my_children(
    is_active: bool | None = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all direct child links for the authenticated user's account.

    Returns 404 if the user is not a corporate account member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_children(db, account_id, is_active=is_active)


@router.get(
    "/corporate/admin/hierarchy/parents",
    response_model=HierarchyLinkListResponse,
    summary="Account admin: list parent accounts in my hierarchy",
)
async def admin_list_my_parents(
    is_active: bool | None = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all direct parent links for the authenticated user's account.

    Returns 404 if the user is not a corporate account member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_parents(db, account_id, is_active=is_active)
