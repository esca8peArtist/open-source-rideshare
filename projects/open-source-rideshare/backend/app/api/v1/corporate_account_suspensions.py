"""Corporate Account Suspension & Reinstatement endpoints.

Platform-admin endpoints (require_admin):
  POST /corporate/accounts/{account_id}/suspend      — suspend an account
  POST /corporate/accounts/{account_id}/reinstate    — reinstate an account
  GET  /corporate/accounts/{account_id}/suspension   — get active suspension
  GET  /corporate/accounts/{account_id}/suspension/history — suspension history
  GET  /admin/corporate/suspensions                  — list all suspended accounts

Member endpoint (authenticated member of the account):
  GET  /corporate/suspension/status                  — own account suspension status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_account_suspension import (
    ReinstateRequest,
    SuspendRequest,
    SuspensionListResponse,
    SuspensionResponse,
    SuspensionStatusResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_account_suspension import (
    get_active_suspension,
    is_account_suspended,
    list_all_suspended_accounts,
    list_suspension_history,
    reinstate_account,
    suspend_account,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-suspensions"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Resolve the corporate account ID for an authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Platform-admin: suspend an account
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/{account_id}/suspend",
    response_model=SuspensionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: suspend a corporate account",
)
async def admin_suspend_account(
    account_id: int,
    payload: SuspendRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Suspend a corporate account for billing, compliance, or policy reasons.

    Creates a new suspension record.  Only one active suspension is permitted
    per account; returns HTTP 409 when the account is already suspended.

    Platform admin only.
    """
    return await suspend_account(
        db,
        account_id=account_id,
        suspended_by_id=_admin.id,
        reason=payload.reason,
        note=payload.suspension_note,
    )


# ---------------------------------------------------------------------------
# Platform-admin: reinstate an account
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/{account_id}/reinstate",
    response_model=SuspensionResponse,
    summary="Admin: reinstate a suspended corporate account",
)
async def admin_reinstate_account(
    account_id: int,
    payload: ReinstateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reinstate a previously suspended corporate account.

    Marks the active suspension as resolved.  Returns HTTP 404 when the
    account does not have an active suspension.

    Platform admin only.
    """
    return await reinstate_account(
        db,
        account_id=account_id,
        reinstated_by_id=_admin.id,
        reinstatement_note=payload.reinstatement_note,
    )


# ---------------------------------------------------------------------------
# Platform-admin: get active suspension
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/{account_id}/suspension",
    response_model=SuspensionResponse,
    summary="Admin: get active suspension for a corporate account",
)
async def admin_get_active_suspension(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the active suspension record for a corporate account.

    Returns HTTP 404 when the account is not currently suspended.

    Platform admin only.
    """
    suspension = await get_active_suspension(db, account_id)
    if suspension is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This account does not have an active suspension.",
        )
    return suspension


# ---------------------------------------------------------------------------
# Platform-admin: suspension history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/{account_id}/suspension/history",
    response_model=SuspensionListResponse,
    summary="Admin: get suspension history for a corporate account",
)
async def admin_get_suspension_history(
    account_id: int,
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all suspension records for a corporate account, most recent first.

    Includes both active and resolved (reinstated) suspensions.

    Platform admin only.
    """
    records = await list_suspension_history(db, account_id, skip=skip, limit=limit)
    return SuspensionListResponse(
        suspensions=list(records),
        total=len(records),
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all suspended accounts
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/suspensions",
    response_model=SuspensionListResponse,
    summary="Admin: list all currently suspended corporate accounts",
)
async def admin_list_all_suspensions(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all currently active suspensions across all corporate accounts.

    Ordered by most recently suspended first.  Intended for platform-admin
    oversight dashboards and compliance reviews.

    Platform admin only.
    """
    records = await list_all_suspended_accounts(db, skip=skip, limit=limit)
    return SuspensionListResponse(
        suspensions=list(records),
        total=len(records),
    )


# ---------------------------------------------------------------------------
# Member: own account suspension status
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/suspension/status",
    response_model=SuspensionStatusResponse,
    summary="Get suspension status for own corporate account",
)
async def get_my_suspension_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the suspension status of the requesting user's corporate account.

    Members can use this endpoint to check whether their account is currently
    suspended and to view the publicly visible reason.  Returns HTTP 404 when
    the user is not a member of any corporate account.
    """
    account_id = await _get_member_account_id(db, user.id)
    suspension = await get_active_suspension(db, account_id)

    if suspension is None:
        return SuspensionStatusResponse(
            is_suspended=False,
            suspended_at=None,
            reason=None,
            suspension_note=None,
        )

    return SuspensionStatusResponse(
        is_suspended=True,
        suspended_at=suspension.suspended_at,
        reason=suspension.reason.value if hasattr(suspension.reason, "value") else suspension.reason,
        suspension_note=suspension.suspension_note,
    )
