"""Corporate Member Fine-Grained Permissions endpoints.

Enterprise admins grant specific named permission scopes to individual
members beyond the binary admin/member role.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/permissions/my                         — my permissions
  GET  /corporate/accounts/me/permissions/{member_id}                — member's permissions
  GET  /corporate/accounts/me/permissions/{permission_id}/check-scope — check my own scope

Admin endpoints (account-admin only):
  POST   /corporate/accounts/me/permissions                          — grant permission (201)
  GET    /corporate/accounts/me/permissions                          — list all account grants
  GET    /corporate/accounts/me/permissions/summary                  — counts by scope
  GET    /corporate/accounts/me/permissions/scope/{scope}            — members with scope
  DELETE /corporate/accounts/me/permissions/{permission_id}          — revoke (204)

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{account_id}/permissions            — list all grants
  GET  /admin/corporate/accounts/{account_id}/permissions/{member_id} — member grants
  DELETE /admin/corporate/accounts/{account_id}/permissions/{permission_id} — revoke
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_member_permission import PermissionScope
from app.models.user import User
from app.schemas.corporate_member_permission import (
    PermissionCheckResponse,
    PermissionGrantRequest,
    PermissionListResponse,
    PermissionResponse,
    PermissionSummaryResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_member_permission import (
    get_members_with_scope,
    get_permission,
    get_permission_summary,
    grant_permission,
    has_permission,
    list_account_permissions,
    list_all_platform,
    list_member_permissions,
    revoke_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-member-permissions"])


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


def _to_response(entry) -> PermissionResponse:
    return PermissionResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Member: list my own permissions — declared FIRST to avoid path collisions
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/permissions/my",
    response_model=PermissionListResponse,
    summary="Member: list my own active permission scopes",
)
async def list_my_permissions(
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all permission scopes currently granted to the caller."""
    account_id = await _resolve_account_id(db, user.id)
    entries = await list_member_permissions(
        db, account_id=account_id, member_id=user.id, active_only=active_only
    )
    return PermissionListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Admin: grant permission — declared before GET /corporate/accounts/me/permissions
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/permissions",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: grant a permission scope to a member",
)
async def grant_member_permission(
    data: PermissionGrantRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grant a named permission scope to a member.

    Returns 409 if the member already holds an active grant for this scope.
    Re-activates a previously revoked grant (upsert semantics).
    """
    account_id = await _resolve_account_id(db, user.id)
    entry = await grant_permission(
        db,
        account_id=account_id,
        member_id=data.member_id,
        scope=data.permission_scope,
        granted_by_id=user.id,
        expires_at=data.expires_at,
        notes=data.notes,
    )
    await db.commit()
    return _to_response(entry)


# ---------------------------------------------------------------------------
# Admin: list all account grants — declared BEFORE /{permission_id} paths
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/permissions",
    response_model=PermissionListResponse,
    summary="Admin: list all permission grants for my corporate account",
)
async def list_account_permission_grants(
    scope: PermissionScope | None = Query(None, description="Filter by scope."),
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all permission grants for the caller's corporate account."""
    account_id = await _resolve_account_id(db, user.id)
    entries = await list_account_permissions(
        db,
        account_id=account_id,
        scope=scope,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return PermissionListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Admin: summary — declared BEFORE /{permission_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/permissions/summary",
    response_model=PermissionSummaryResponse,
    summary="Admin: get permission grant counts by scope",
)
async def get_account_permission_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active permission grant counts grouped by scope."""
    account_id = await _resolve_account_id(db, user.id)
    summary = await get_permission_summary(db, account_id=account_id)
    return PermissionSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# Admin: members with a specific scope — declared BEFORE /{permission_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/permissions/scope/{scope}",
    response_model=PermissionListResponse,
    summary="Admin: list all members who hold a specific permission scope",
)
async def list_members_with_scope(
    scope: PermissionScope,
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all members currently holding the specified permission scope."""
    account_id = await _resolve_account_id(db, user.id)
    entries = await get_members_with_scope(
        db, account_id=account_id, scope=scope, active_only=active_only
    )
    return PermissionListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Member: list permissions for a specific member
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/permissions/member/{member_id}",
    response_model=PermissionListResponse,
    summary="Member: list permissions for a specific member in my account",
)
async def list_member_permission_grants(
    member_id: int,
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all permission grants for a specific member in the caller's account."""
    account_id = await _resolve_account_id(db, user.id)
    entries = await list_member_permissions(
        db, account_id=account_id, member_id=member_id, active_only=active_only
    )
    return PermissionListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Member: check whether a member holds a scope
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/permissions/check",
    response_model=PermissionCheckResponse,
    summary="Member: check whether a member holds a specific permission scope",
)
async def check_member_permission(
    member_id: int = Query(..., description="Member user ID to check."),
    scope: PermissionScope = Query(..., description="Permission scope to check."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a boolean indicating whether *member_id* holds *scope*.

    Never raises 404 — returns ``has_permission: false`` when the member
    does not hold the scope.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await has_permission(
        db, account_id=account_id, member_id=member_id, scope=scope
    )
    return PermissionCheckResponse(
        account_id=account_id,
        member_id=member_id,
        permission_scope=scope,
        has_permission=result,
    )


# ---------------------------------------------------------------------------
# Admin: revoke permission
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: revoke a permission grant",
)
async def revoke_member_permission(
    permission_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the permission grant with the given id (soft-delete: is_active=False).

    Raises 404 if the entry does not exist or is already revoked.
    """
    account_id = await _resolve_account_id(db, user.id)
    await revoke_permission(db, account_id=account_id, permission_id=permission_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Platform-admin: list grants for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/permissions",
    response_model=PermissionListResponse,
    summary="Platform admin: list all permission grants for a corporate account",
)
async def platform_admin_list_permissions(
    account_id: int,
    scope: PermissionScope | None = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all permission grants for any corporate account."""
    entries = await list_account_permissions(
        db,
        account_id=account_id,
        scope=scope,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return PermissionListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Platform-admin: list grants for a specific member in any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/permissions/member/{member_id}",
    response_model=PermissionListResponse,
    summary="Platform admin: list permission grants for a member in any account",
)
async def platform_admin_list_member_permissions(
    account_id: int,
    member_id: int,
    active_only: bool = Query(True),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all permission grants for a specific member in any account."""
    entries = await list_member_permissions(
        db, account_id=account_id, member_id=member_id, active_only=active_only
    )
    return PermissionListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Platform-admin: revoke a grant in any account
# ---------------------------------------------------------------------------


@router.delete(
    "/admin/corporate/accounts/{account_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Platform admin: revoke a permission grant in any corporate account",
)
async def platform_admin_revoke_permission(
    account_id: int,
    permission_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a permission grant for any corporate account."""
    await revoke_permission(db, account_id=account_id, permission_id=permission_id)
    await db.commit()
