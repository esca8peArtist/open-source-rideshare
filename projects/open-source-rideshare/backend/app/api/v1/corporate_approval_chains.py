"""Corporate Multi-Level Approval Chain endpoints.

Admin endpoints (require _require_account_admin):
  POST   /corporate/accounts/{account_id}/approval-chains
  GET    /corporate/accounts/{account_id}/approval-chains
  GET    /corporate/accounts/{account_id}/approval-chains/{chain_id}
  PUT    /corporate/accounts/{account_id}/approval-chains/{chain_id}
  POST   /corporate/accounts/{account_id}/approval-chains/{chain_id}/deactivate
  DELETE /corporate/accounts/{account_id}/approval-chains/{chain_id}
  GET    /corporate/accounts/{account_id}/approval-requests/pending-review

Step decision (admin/approver):
  POST   /corporate/accounts/{account_id}/approval-requests/{request_id}/decide

Member endpoints (get_current_user + account membership):
  GET    /corporate/accounts/me/approval-chains/applicable
  POST   /corporate/accounts/me/approval-requests
  GET    /corporate/accounts/me/approval-requests
  GET    /corporate/accounts/me/approval-requests/{request_id}
  POST   /corporate/accounts/me/approval-requests/{request_id}/cancel

Platform-admin (require_admin):
  GET    /admin/corporate/approval-chains
  GET    /admin/corporate/approval-requests
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_approval_chain import (
    ApprovalChainCreate,
    ApprovalChainListResponse,
    ApprovalChainResponse,
    ApprovalChainUpdate,
    ChainRequestCreate,
    ChainRequestListResponse,
    ChainRequestResponse,
    StepDecisionRequest,
)
from app.services.corporate_account_mgmt import (
    _require_account_admin,
    get_user_account,
)
from app.services.corporate_approval_chain import (
    cancel_request,
    create_chain,
    deactivate_chain,
    decide_step,
    delete_chain,
    find_applicable_chain,
    get_chain,
    get_chain_request,
    list_all_chains,
    list_all_requests,
    list_chains,
    list_pending_for_approver,
    list_requests,
    start_chain_request,
    update_chain,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-approval-chains"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_member_account(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID for the authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ===========================================================================
# Admin endpoints
# ===========================================================================


@router.post(
    "/corporate/accounts/{account_id}/approval-chains",
    response_model=ApprovalChainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new approval chain",
)
async def admin_create_chain(
    account_id: int,
    payload: ApprovalChainCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new multi-step approval chain for the corporate account.

    Steps must have sequential step_order values starting from 1.
    Returns HTTP 422 if step order is invalid.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await create_chain(db, account_id, payload, created_by_id=user.id)


@router.get(
    "/corporate/accounts/{account_id}/approval-chains",
    response_model=ApprovalChainListResponse,
    summary="Admin: list approval chains on the account",
)
async def admin_list_chains(
    account_id: int,
    is_active: Optional[bool] = Query(
        None, description="Filter by active status"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all approval chains for the corporate account.

    Optionally filter by is_active.  Sorted newest first.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    chains = await list_chains(db, account_id, is_active=is_active)
    return ApprovalChainListResponse(chains=chains, total=len(chains))


@router.get(
    "/corporate/accounts/{account_id}/approval-chains/{chain_id}",
    response_model=ApprovalChainResponse,
    summary="Admin: get a single approval chain",
)
async def admin_get_chain(
    account_id: int,
    chain_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single approval chain by ID.

    Returns HTTP 404 when chain not found or belongs to a different account.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await get_chain(db, chain_id=chain_id, account_id=account_id)


@router.put(
    "/corporate/accounts/{account_id}/approval-chains/{chain_id}",
    response_model=ApprovalChainResponse,
    summary="Admin: update an approval chain",
)
async def admin_update_chain(
    account_id: int,
    chain_id: int,
    payload: ApprovalChainUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an approval chain.

    If steps are provided, all existing steps are replaced.
    Returns HTTP 404 when chain not found; HTTP 422 if new step order is invalid.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await update_chain(db, chain_id=chain_id, account_id=account_id, data=payload)


@router.post(
    "/corporate/accounts/{account_id}/approval-chains/{chain_id}/deactivate",
    response_model=ApprovalChainResponse,
    summary="Admin: deactivate an approval chain",
)
async def admin_deactivate_chain(
    account_id: int,
    chain_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an approval chain as inactive so it no longer applies to new rides.

    Returns HTTP 404 if not found; HTTP 409 if already inactive.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await deactivate_chain(db, chain_id=chain_id, account_id=account_id)


@router.delete(
    "/corporate/accounts/{account_id}/approval-chains/{chain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: delete an approval chain",
)
async def admin_delete_chain(
    account_id: int,
    chain_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete an approval chain.

    Returns HTTP 404 if not found; HTTP 409 if there are pending requests.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    await delete_chain(db, chain_id=chain_id, account_id=account_id)


@router.get(
    "/corporate/accounts/{account_id}/approval-requests/pending-review",
    response_model=ChainRequestListResponse,
    summary="Admin: list approval requests pending admin review",
)
async def admin_list_pending_review(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return pending approval requests where the current step targets this admin.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    requests = await list_pending_for_approver(
        db, account_id=account_id, approver_id=user.id
    )
    return ChainRequestListResponse(requests=requests, total=len(requests))


# ===========================================================================
# Step decision (admin/approver)
# ===========================================================================


@router.post(
    "/corporate/accounts/{account_id}/approval-requests/{request_id}/decide",
    response_model=ChainRequestResponse,
    summary="Admin/approver: record a decision on the current step",
)
async def admin_decide_step(
    account_id: int,
    request_id: int,
    payload: StepDecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record an approval or denial decision for the current step of a request.

    On approval: advances to the next step, or fully approves if last step.
    On denial: closes the request immediately.

    Returns HTTP 404 if request not found; HTTP 409 if not pending;
    HTTP 403 if user is not the designated approver for a specific_user step.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await decide_step(
        db,
        request_id=request_id,
        account_id=account_id,
        approver_id=user.id,
        decision=payload.decision.value,
        note=payload.note,
    )


# ===========================================================================
# Member endpoints
# ===========================================================================


@router.get(
    "/corporate/accounts/me/approval-chains/applicable",
    response_model=Optional[ApprovalChainResponse],
    summary="Member: find the applicable approval chain for a ride",
)
async def member_find_applicable_chain(
    estimated_cost_usd: Optional[float] = Query(
        None, ge=0, description="Estimated ride cost in USD"
    ),
    cost_center_id: Optional[int] = Query(
        None, description="Cost center ID for the ride"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the most specific active approval chain applicable to the given
    ride context, or null if no chain matches.

    Returns HTTP 404 if the user is not a corporate account member.
    """
    account_id = await _resolve_member_account(db, user.id)
    return await find_applicable_chain(
        db,
        account_id,
        estimated_cost_usd=estimated_cost_usd,
        cost_center_id=cost_center_id,
    )


@router.post(
    "/corporate/accounts/me/approval-requests",
    response_model=ChainRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Member: start a new approval request",
)
async def member_start_request(
    payload: ChainRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new multi-step approval request on the specified chain.

    Returns HTTP 404 if user is not a member or chain not found;
    HTTP 409 if the chain is inactive.
    """
    account_id = await _resolve_member_account(db, user.id)
    return await start_chain_request(
        db,
        chain_id=payload.chain_id,
        account_id=account_id,
        requester_id=user.id,
        data=payload,
    )


@router.get(
    "/corporate/accounts/me/approval-requests",
    response_model=ChainRequestListResponse,
    summary="Member: list own approval requests",
)
async def member_list_own_requests(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by status (pending/approved/denied/cancelled)",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated member's own approval requests.

    Returns HTTP 404 if user is not a corporate account member.
    """
    account_id = await _resolve_member_account(db, user.id)
    requests = await list_requests(
        db,
        account_id=account_id,
        status=status_filter,
        requester_id=user.id,
    )
    return ChainRequestListResponse(requests=requests, total=len(requests))


@router.get(
    "/corporate/accounts/me/approval-requests/{request_id}",
    response_model=ChainRequestResponse,
    summary="Member: get own approval request",
)
async def member_get_own_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single approval request by ID.

    Returns HTTP 404 if user is not a member or request not found.
    """
    account_id = await _resolve_member_account(db, user.id)
    return await get_chain_request(db, request_id=request_id, account_id=account_id)


@router.post(
    "/corporate/accounts/me/approval-requests/{request_id}/cancel",
    response_model=ChainRequestResponse,
    summary="Member: cancel an approval request",
)
async def member_cancel_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending approval request.

    Returns HTTP 404 if user is not a member or request not found;
    HTTP 409 if request is not pending.
    """
    account_id = await _resolve_member_account(db, user.id)
    return await cancel_request(
        db,
        request_id=request_id,
        account_id=account_id,
        requester_id=user.id,
    )


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.get(
    "/admin/corporate/approval-chains",
    response_model=ApprovalChainListResponse,
    summary="Platform admin: list approval chains across all accounts",
)
async def platform_admin_list_chains(
    account_id: Optional[int] = Query(None, description="Filter to a single account"),
    limit: int = Query(200, ge=1, le=500, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List approval chains across all corporate accounts.

    Platform admin only.
    """
    chains = await list_all_chains(
        db, account_id=account_id, limit=limit, offset=offset
    )
    return ApprovalChainListResponse(chains=chains, total=len(chains))


@router.get(
    "/admin/corporate/approval-requests",
    response_model=ChainRequestListResponse,
    summary="Platform admin: list approval requests across all accounts",
)
async def platform_admin_list_requests(
    account_id: Optional[int] = Query(None, description="Filter to a single account"),
    limit: int = Query(200, ge=1, le=500, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List approval requests across all corporate accounts.

    Platform admin only.
    """
    requests = await list_all_requests(
        db, account_id=account_id, limit=limit, offset=offset
    )
    return ChainRequestListResponse(requests=requests, total=len(requests))
