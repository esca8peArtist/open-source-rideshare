"""Corporate Account Contract endpoints.

Account-member endpoints (any active account member):
  GET  /corporate/accounts/me/contract

Platform-admin endpoints (require_admin):
  GET  /admin/corporate/accounts/{account_id}/contracts
  POST /admin/corporate/accounts/{account_id}/contracts
  GET  /admin/corporate/contracts/expiring
  GET  /admin/corporate/contracts/{contract_id}
  PATCH /admin/corporate/contracts/{contract_id}
  POST /admin/corporate/contracts/{contract_id}/activate
  POST /admin/corporate/contracts/{contract_id}/terminate
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_account_contract import ContractStatus
from app.models.user import User
from app.schemas.corporate_account_contract import (
    ContractCreate,
    ContractListResponse,
    ContractResponse,
    ContractUpdate,
    TerminateRequest,
)
from app.services.corporate_account_contract import (
    activate_contract,
    create_contract,
    get_active_contract,
    get_contract,
    list_contracts,
    list_expiring_contracts,
    terminate_contract,
    update_contract,
)
from app.services.corporate_account_mgmt import get_user_account

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-contracts"])


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
# Member endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/contract",
    response_model=ContractResponse,
    summary="Get the active contract for the authenticated user's corporate account",
)
async def get_my_active_contract(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently active service contract for the caller's corporate account.

    Any active account member may call this endpoint.  Returns HTTP 404 when the
    caller is not a member of any account, or when no active contract exists.
    """
    account_id = await _get_member_account_id(db, user.id)
    contract = await get_active_contract(db, account_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active contract found for your account.",
        )
    return contract


# ---------------------------------------------------------------------------
# Platform-admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/contracts",
    response_model=ContractListResponse,
    summary="Admin: list contracts for a corporate account",
)
async def admin_list_contracts(
    account_id: int,
    status: Optional[str] = Query(None, description="Filter by contract status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all contracts for the specified corporate account (platform admin only).

    Optionally filter by status using the ``?status=`` query parameter.  Supports
    offset-based pagination via ``skip`` and ``limit``.
    """
    status_filter: ContractStatus | None = None
    if status is not None:
        try:
            status_filter = ContractStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value '{status}'. Must be one of: {[s.value for s in ContractStatus]}",
            )
    return await list_contracts(db, account_id, status_filter, skip, limit)


@router.post(
    "/admin/corporate/accounts/{account_id}/contracts",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a draft contract for a corporate account",
)
async def admin_create_contract(
    account_id: int,
    body: ContractCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new draft service contract for the specified corporate account.

    Returns HTTP 409 if an active contract already exists for this account.
    The contract number is auto-generated when not supplied in the request body.
    """
    return await create_contract(db, account_id, body, _admin.id)


@router.get(
    "/admin/corporate/contracts/expiring",
    response_model=ContractListResponse,
    summary="Admin: list active contracts expiring within a given window",
)
async def admin_list_expiring_contracts(
    within_days: int = Query(30, ge=1, description="Look-ahead window in days"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return active contracts whose end date falls within ``within_days`` days.

    This endpoint must be declared before ``/admin/corporate/contracts/{contract_id}``
    so that FastAPI does not attempt to parse the literal string "expiring" as a
    contract ID path parameter.
    """
    return await list_expiring_contracts(db, within_days, skip, limit)


@router.get(
    "/admin/corporate/contracts/{contract_id}",
    response_model=ContractResponse,
    summary="Admin: get a contract by ID",
)
async def admin_get_contract(
    contract_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a single contract by its primary key (platform admin only).

    Raises HTTP 404 when the contract does not exist.
    """
    return await get_contract(db, contract_id)


@router.patch(
    "/admin/corporate/contracts/{contract_id}",
    response_model=ContractResponse,
    summary="Admin: partially update a contract",
)
async def admin_update_contract(
    contract_id: int,
    body: ContractUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a draft or active contract (platform admin only).

    Returns HTTP 404 when the contract does not exist.  Returns HTTP 409 when
    the contract is in a terminal state (terminated or expired).
    """
    return await update_contract(db, contract_id, body, _admin.id)


@router.post(
    "/admin/corporate/contracts/{contract_id}/activate",
    response_model=ContractResponse,
    summary="Admin: activate a draft contract",
)
async def admin_activate_contract(
    contract_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Move a draft contract to active status (platform admin only).

    Any existing active contract for the same account is automatically moved to
    expired before the target contract is activated.  Returns HTTP 409 if the
    target contract is not in draft status.
    """
    return await activate_contract(db, contract_id, _admin.id)


@router.post(
    "/admin/corporate/contracts/{contract_id}/terminate",
    response_model=ContractResponse,
    summary="Admin: terminate an active contract",
)
async def admin_terminate_contract(
    contract_id: int,
    body: TerminateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Terminate an active contract (platform admin only).

    A mandatory termination reason must be supplied in the request body.
    Returns HTTP 409 if the contract is not currently active.
    """
    return await terminate_contract(db, contract_id, _admin.id, body.reason)
