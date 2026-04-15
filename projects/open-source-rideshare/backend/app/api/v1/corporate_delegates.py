"""Corporate Delegate Access endpoints.

Enterprise assistants can be granted the ability to book rides on behalf of
other employees.  Admins manage delegations; members can inspect their own.

Member endpoints (any active account member):
  GET  /corporate/accounts/me/delegates/my-principals      — list principals I can book for
  GET  /corporate/accounts/me/delegates/my-delegates        — list who can book for me
  POST /corporate/accounts/me/delegates/check-permission    — check delegation permission
  GET  /corporate/accounts/me/delegates/{delegation_id}     — get specific delegation

Admin endpoints (require ADMIN role within the account):
  POST   /corporate/accounts/me/delegates                        — grant delegate access
  PUT    /corporate/accounts/me/delegates/{delegation_id}        — update delegation
  DELETE /corporate/accounts/me/delegates/{delegation_id}/revoke — revoke delegation

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/delegates                          — list all
  GET /admin/corporate/accounts/{account_id}/delegates/{delegation_id}          — get one
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_delegate import (
    DelegateCreate,
    DelegateListResponse,
    DelegatePermissionCheck,
    DelegatePermissionResult,
    DelegateResponse,
    DelegateUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_delegate import (
    check_delegate_permission,
    get_delegate,
    grant_delegate_access,
    list_all_delegates,
    list_my_delegates,
    list_my_principals,
    revoke_delegate_access,
    update_delegate_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-delegates"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list principals I can book for (specific path — must be before /{id})
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/delegates/my-principals",
    response_model=DelegateListResponse,
    summary="List principals I can book rides for",
)
async def list_principals_i_can_book_for(
    active_only: bool = Query(True, description="When True, only return active, non-expired delegations."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return delegations where the current user is the delegate.

    Shows which employees the caller is permitted to book rides for.
    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_my_principals(db, account_id, user.id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Member: list who can book for me (specific path — must be before /{id})
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/delegates/my-delegates",
    response_model=DelegateListResponse,
    summary="List delegates who can book rides for me",
)
async def list_delegates_who_can_book_for_me(
    active_only: bool = Query(True, description="When True, only return active, non-expired delegations."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return delegations where the current user is the principal.

    Shows which employees are permitted to book rides on the caller's behalf.
    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_my_delegates(db, account_id, user.id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Member: check delegation permission (specific path — must be before /{id})
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/delegates/check-permission",
    response_model=DelegatePermissionResult,
    summary="Check whether a delegate may book a ride for a principal",
)
async def check_permission(
    data: DelegatePermissionCheck,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check delegation permission without raising errors.

    Returns a DelegatePermissionResult indicating whether the booking would be
    allowed, along with a human-readable reason.
    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await check_delegate_permission(
        db,
        account_id,
        data.delegate_user_id,
        data.principal_user_id,
        estimated_cost=data.estimated_ride_cost_usd,
    )


# ---------------------------------------------------------------------------
# Admin: grant delegate access
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/delegates",
    response_model=DelegateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: grant delegate access",
)
async def grant_access(
    data: DelegateCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grant a delegate user the ability to book rides for a principal.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await grant_delegate_access(db, account_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Member: get a specific delegation (parameterized — after all specific paths)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/delegates/{delegation_id}",
    response_model=DelegateResponse,
    summary="Get a specific delegation by ID",
)
async def get_delegation(
    delegation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific delegation.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_delegate(db, account_id, delegation_id)


# ---------------------------------------------------------------------------
# Admin: update delegation
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/delegates/{delegation_id}",
    response_model=DelegateResponse,
    summary="Admin: update a delegation",
)
async def update_delegation(
    delegation_id: int,
    data: DelegateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing delegation.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await update_delegate_access(db, account_id, delegation_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: revoke delegation
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/delegates/{delegation_id}/revoke",
    response_model=DelegateResponse,
    summary="Admin: revoke a delegation (soft-delete)",
)
async def revoke_delegation(
    delegation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (soft-delete) a delegation.

    The delegation record is preserved for audit purposes but is_active is set
    to False.  Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await revoke_delegate_access(db, account_id, delegation_id, user.id)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Platform-admin: list all delegations for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/delegates",
    response_model=DelegateListResponse,
    summary="Platform admin: list delegations for any corporate account",
)
async def platform_admin_list_delegates(
    account_id: int,
    active_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all delegations for any corporate account.

    Requires platform-level admin role.
    """
    return await list_all_delegates(db, account_id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: get one delegation for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/delegates/{delegation_id}",
    response_model=DelegateResponse,
    summary="Platform admin: get a specific delegation for any corporate account",
)
async def platform_admin_get_delegate(
    account_id: int,
    delegation_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific delegation for any corporate account.

    Requires platform-level admin role.
    """
    return await get_delegate(db, account_id, delegation_id)
