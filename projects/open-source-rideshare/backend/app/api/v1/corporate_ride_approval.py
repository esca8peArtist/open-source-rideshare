"""Corporate Ride Approval API endpoints.

Employees request pre-booking approvals; account admins approve or deny.
An approval code is verified at booking time before charging to the corporate
account.

Member routes (/api/v1/corporate/accounts/me/approvals):
  POST   /corporate/accounts/me/approvals              — request approval
  GET    /corporate/accounts/me/approvals              — list own requests
  DELETE /corporate/accounts/me/approvals/{id}         — cancel own pending request

Account-admin routes (subset of member routes — all members can read):
  GET    /corporate/accounts/me/approvals/pending      — all pending requests for review
  PUT    /corporate/accounts/me/approvals/{id}/approve — approve a request
  PUT    /corporate/accounts/me/approvals/{id}/deny    — deny a request

Verification route:
  POST   /corporate/accounts/me/approvals/verify       — verify approval code before booking

Platform-admin routes:
  GET    /admin/corporate/accounts/{account_id}/approvals — view any account's approvals
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_ride_approval import (
    ApprovalVerifyRequest,
    ApprovalVerifyResponse,
    CorporateRideApprovalResponse,
    RideApprovalDecision,
    RideApprovalRequest,
    RideDenialRequest,
)
from app.services.corporate_ride_approval import (
    approve,
    cancel,
    deny,
    list_member_approvals,
    list_pending_approvals,
    request_approval,
    verify_approval,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-ride-approvals"])


# ---------------------------------------------------------------------------
# Helper: resolve the caller's account_id
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID the user belongs to.

    Raises HTTP 404 if the user is not an active member of any account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return membership.account_id


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/approvals",
    response_model=CorporateRideApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a pre-booking ride approval",
)
async def create_approval_request(
    data: RideApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a ride approval request to the account admin.

    Employees describe their trip (purpose, destination, estimated cost) and
    request permission before booking.  Approved requests generate a code that
    must be presented when booking the ride.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    approval = await request_approval(db, account_id, current_user.id, data)
    return CorporateRideApprovalResponse.model_validate(approval)


@router.get(
    "/corporate/accounts/me/approvals",
    response_model=list[CorporateRideApprovalResponse],
    summary="List own ride approval requests",
)
async def list_my_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all approval requests submitted by the calling member (newest first)."""
    account_id = await _get_member_account_id(db, current_user.id)
    approvals = await list_member_approvals(db, account_id, current_user.id)
    return [CorporateRideApprovalResponse.model_validate(a) for a in approvals]


@router.delete(
    "/corporate/accounts/me/approvals/{approval_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel own pending ride approval request",
)
async def cancel_my_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending approval request.

    Only the original requester may cancel, and only while the request is
    still PENDING.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    await cancel(db, approval_id, account_id, current_user.id)


# ---------------------------------------------------------------------------
# Account-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/approvals/pending",
    response_model=list[CorporateRideApprovalResponse],
    summary="List all pending ride approval requests (account admin only)",
)
async def list_pending(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all pending approval requests for the admin's account, oldest first.

    Only account admins may call this endpoint.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    approvals = await list_pending_approvals(db, account_id)
    return [CorporateRideApprovalResponse.model_validate(a) for a in approvals]


@router.put(
    "/corporate/accounts/me/approvals/{approval_id}/approve",
    response_model=CorporateRideApprovalResponse,
    summary="Approve a pending ride request (account admin only)",
)
async def approve_request(
    approval_id: int,
    data: RideApprovalDecision,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a pending ride approval request.

    Optionally set a maximum cost ceiling the employee may spend on this ride.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    approval = await approve(db, approval_id, account_id, current_user.id, data)
    return CorporateRideApprovalResponse.model_validate(approval)


@router.put(
    "/corporate/accounts/me/approvals/{approval_id}/deny",
    response_model=CorporateRideApprovalResponse,
    summary="Deny a pending ride request (account admin only)",
)
async def deny_request(
    approval_id: int,
    data: RideDenialRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deny a pending ride approval request, with an optional reason."""
    account_id = await _get_member_account_id(db, current_user.id)
    approval = await deny(db, approval_id, account_id, current_user.id, data)
    return CorporateRideApprovalResponse.model_validate(approval)


# ---------------------------------------------------------------------------
# Verification route
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/approvals/verify",
    response_model=ApprovalVerifyResponse,
    summary="Verify an approval code before booking",
)
async def verify_approval_code(
    data: ApprovalVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check whether an approval code is valid for booking.

    Returns ``{valid: true, approval_id, max_cost_usd}`` on success, or
    ``{valid: false, reason}`` with a human-readable explanation on failure.
    Any active account member may call this endpoint.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await verify_approval(
        db,
        account_id=account_id,
        approval_code=data.approval_code,
        estimated_cost_usd=data.estimated_cost_usd,
    )


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/approvals",
    response_model=list[CorporateRideApprovalResponse],
    summary="[Admin] List all approval requests for a corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_approvals(
    account_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return all approval requests for any corporate account (platform admin only)."""
    from app.models.corporate_ride_approval import CorporateRideApproval

    result = await db.execute(
        select(CorporateRideApproval)
        .where(CorporateRideApproval.account_id == account_id)
        .order_by(CorporateRideApproval.requested_at.desc())
    )
    all_approvals = result.scalars().all()
    return [CorporateRideApprovalResponse.model_validate(a) for a in all_approvals]
