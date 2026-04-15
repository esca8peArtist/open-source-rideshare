"""Service layer for Corporate Ride Approval.

Employees request pre-booking approval; account admins approve or deny.
Approved requests carry a unique code verified at booking time.

Functions
---------
    request_approval        — employee submits an approval request
    list_pending_approvals  — account admin view: all pending requests
    list_member_approvals   — employee view: their own requests
    get_approval            — fetch a single approval by ID
    approve                 — admin approves a pending request
    deny                    — admin denies a pending request
    cancel                  — employee cancels their own pending request
    verify_approval         — booking-time code verification
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_ride_approval import ApprovalStatus, CorporateRideApproval
from app.schemas.corporate_ride_approval import (
    ApprovalVerifyResponse,
    RideApprovalDecision,
    RideApprovalRequest,
    RideDenialRequest,
)

# How many pending approvals a member may hold concurrently (anti-spam)
MAX_PENDING_PER_MEMBER = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> None:
    """Raise HTTP 403 if the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )


async def _require_active_member(
    db: AsyncSession, account_id: int, user_id: int
) -> None:
    """Raise HTTP 403 if the user is not an active member of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


async def request_approval(
    db: AsyncSession,
    account_id: int,
    requester_user_id: int,
    data: RideApprovalRequest,
) -> CorporateRideApproval:
    """Submit a new ride approval request.

    Business rules:
    - Requester must be an active member of the account.
    - Member may not exceed MAX_PENDING_PER_MEMBER concurrent pending requests.
    - Approval is created in PENDING status.
    - approval_code is a UUID; expires_at is set from data.validity_hours but
      uses UTC now + validity_hours as the *absolute* expiry (the timer starts
      when the request is submitted, not when it is approved — employees should
      plan ahead).

    Raises:
        HTTPException 400: Concurrent pending limit exceeded.
        HTTPException 403: Requester is not an active member.
    """
    await _require_active_member(db, account_id, requester_user_id)

    # Guard: concurrent pending cap
    pending_count_result = await db.execute(
        select(CorporateRideApproval).where(
            CorporateRideApproval.account_id == account_id,
            CorporateRideApproval.requester_user_id == requester_user_id,
            CorporateRideApproval.status == ApprovalStatus.PENDING,
        )
    )
    pending_count = len(pending_count_result.scalars().all())
    if pending_count >= MAX_PENDING_PER_MEMBER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"You already have {MAX_PENDING_PER_MEMBER} pending approval requests. "
                "Cancel or wait for existing requests to be reviewed before submitting more."
            ),
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=data.validity_hours)

    approval = CorporateRideApproval(
        account_id=account_id,
        requester_user_id=requester_user_id,
        purpose=data.purpose,
        destination_description=data.destination_description,
        estimated_cost_usd=data.estimated_cost_usd,
        status=ApprovalStatus.PENDING,
        approval_code=str(uuid.uuid4()),
        expires_at=expires_at,
        requested_at=now,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


async def list_pending_approvals(
    db: AsyncSession,
    account_id: int,
) -> Sequence[CorporateRideApproval]:
    """Return all pending approval requests for an account (oldest first).

    Intended for account admins reviewing their queue.
    """
    result = await db.execute(
        select(CorporateRideApproval)
        .where(
            CorporateRideApproval.account_id == account_id,
            CorporateRideApproval.status == ApprovalStatus.PENDING,
        )
        .order_by(CorporateRideApproval.requested_at.asc())
    )
    return result.scalars().all()


async def list_member_approvals(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> Sequence[CorporateRideApproval]:
    """Return all approval requests submitted by a specific member (newest first)."""
    result = await db.execute(
        select(CorporateRideApproval)
        .where(
            CorporateRideApproval.account_id == account_id,
            CorporateRideApproval.requester_user_id == user_id,
        )
        .order_by(CorporateRideApproval.requested_at.desc())
    )
    return result.scalars().all()


async def get_approval(
    db: AsyncSession,
    approval_id: int,
    account_id: int | None = None,
) -> CorporateRideApproval:
    """Fetch a single approval by ID.

    If ``account_id`` is supplied, raises 404 when the approval does not
    belong to that account (prevents information leakage across accounts).

    Raises:
        HTTPException 404: If the approval is not found.
    """
    q = select(CorporateRideApproval).where(CorporateRideApproval.id == approval_id)
    if account_id is not None:
        q = q.where(CorporateRideApproval.account_id == account_id)

    result = await db.execute(q)
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found.",
        )
    return approval


async def approve(
    db: AsyncSession,
    approval_id: int,
    account_id: int,
    admin_user_id: int,
    data: RideApprovalDecision,
) -> CorporateRideApproval:
    """Approve a pending ride request.

    Business rules:
    - Admin must be an active account admin.
    - Approval must be in PENDING status.
    - sets status=APPROVED, records admin, timestamps, optional cost ceiling.

    Raises:
        HTTPException 400: Approval is not in PENDING status.
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: Approval not found.
    """
    await _require_account_admin(db, account_id, admin_user_id)
    approval = await get_approval(db, approval_id, account_id=account_id)

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve a request with status '{approval.status.value}'.",
        )

    now = datetime.now(timezone.utc)
    approval.status = ApprovalStatus.APPROVED
    approval.approved_by_user_id = admin_user_id
    approval.max_cost_usd = data.max_cost_usd
    approval.review_note = data.review_note
    approval.reviewed_at = now

    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


async def deny(
    db: AsyncSession,
    approval_id: int,
    account_id: int,
    admin_user_id: int,
    data: RideDenialRequest,
) -> CorporateRideApproval:
    """Deny a pending ride request.

    Business rules:
    - Admin must be an active account admin.
    - Approval must be in PENDING status.

    Raises:
        HTTPException 400: Approval is not in PENDING status.
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: Approval not found.
    """
    await _require_account_admin(db, account_id, admin_user_id)
    approval = await get_approval(db, approval_id, account_id=account_id)

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot deny a request with status '{approval.status.value}'.",
        )

    now = datetime.now(timezone.utc)
    approval.status = ApprovalStatus.DENIED
    approval.approved_by_user_id = admin_user_id
    approval.review_note = data.review_note
    approval.reviewed_at = now

    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


async def cancel(
    db: AsyncSession,
    approval_id: int,
    account_id: int,
    requester_user_id: int,
) -> CorporateRideApproval:
    """Cancel a pending approval request.

    Only the original requester may cancel their own request, and only while
    it is still PENDING.

    Raises:
        HTTPException 400: Request is not cancellable (wrong status or wrong owner).
        HTTPException 404: Approval not found.
    """
    approval = await get_approval(db, approval_id, account_id=account_id)

    if approval.requester_user_id != requester_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only cancel your own approval requests.",
        )

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a request with status '{approval.status.value}'.",
        )

    approval.status = ApprovalStatus.CANCELLED
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


async def verify_approval(
    db: AsyncSession,
    account_id: int,
    approval_code: str,
    estimated_cost_usd: Decimal | None,
) -> ApprovalVerifyResponse:
    """Verify an approval code at booking time.

    Checks:
    1. Code exists and belongs to this account.
    2. Status is APPROVED.
    3. Approval has not expired (expires_at > now).
    4. If max_cost_usd is set, estimated_cost_usd must not exceed it.

    Does NOT consume the approval (mark as USED) — that happens when the ride
    is booked.  Returns a structured result so the caller knows why it failed.
    """
    result = await db.execute(
        select(CorporateRideApproval).where(
            CorporateRideApproval.approval_code == approval_code,
            CorporateRideApproval.account_id == account_id,
        )
    )
    approval = result.scalar_one_or_none()

    if approval is None:
        return ApprovalVerifyResponse(
            valid=False,
            reason="Approval code not found or does not belong to this account.",
        )

    if approval.status != ApprovalStatus.APPROVED:
        return ApprovalVerifyResponse(
            valid=False,
            reason=f"Approval is not in APPROVED status (current: {approval.status.value}).",
            approval_id=approval.id,
        )

    now = datetime.now(timezone.utc)
    # Make expires_at timezone-aware for comparison if it isn't already
    expires_at = approval.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        return ApprovalVerifyResponse(
            valid=False,
            reason="Approval has expired.",
            approval_id=approval.id,
        )

    if approval.max_cost_usd is not None and estimated_cost_usd is not None:
        if estimated_cost_usd > approval.max_cost_usd:
            return ApprovalVerifyResponse(
                valid=False,
                reason=(
                    f"Estimated cost ${estimated_cost_usd} exceeds the approved "
                    f"ceiling of ${approval.max_cost_usd}."
                ),
                approval_id=approval.id,
                max_cost_usd=approval.max_cost_usd,
            )

    return ApprovalVerifyResponse(
        valid=True,
        approval_id=approval.id,
        max_cost_usd=approval.max_cost_usd,
    )
