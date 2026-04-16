"""Corporate Mileage Reimbursement endpoints.

Employees submit personal-vehicle mileage claims; admins configure the
per-mile rate and approval thresholds; claims flow through a full lifecycle.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/mileage/policy                       — view policy (200)
  POST /corporate/accounts/me/mileage/claims                       — create draft (201)
  GET  /corporate/accounts/me/mileage/claims                       — list my claims (200)
  GET  /corporate/accounts/me/mileage/claims/{claim_id}            — get claim (200)
  PUT  /corporate/accounts/me/mileage/claims/{claim_id}            — update draft (200)
  POST /corporate/accounts/me/mileage/claims/{claim_id}/submit     — submit (200)

Admin endpoints (account members with admin access):
  PUT  /corporate/accounts/me/mileage/policy                       — update policy (200)
  GET  /corporate/accounts/me/mileage/claims/all                   — list all account claims (200)
  GET  /corporate/accounts/me/mileage/claims/summary               — account summary (200)
  POST /corporate/accounts/me/mileage/claims/{claim_id}/review     — approve or reject (200)
  POST /corporate/accounts/me/mileage/claims/{claim_id}/paid       — mark paid (200)

Platform-admin endpoint:
  GET  /admin/corporate/accounts/{account_id}/mileage              — list all claims (200)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_mileage_reimbursement import ClaimStatus
from app.models.user import User
from app.schemas.corporate_mileage_reimbursement import (
    MileageClaimCreateRequest,
    MileageClaimListResponse,
    MileageClaimResponse,
    MileageClaimReviewRequest,
    MileageClaimSummaryResponse,
    MileageClaimUpdateRequest,
    MileagePolicyResponse,
    MileagePolicyUpdateRequest,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_mileage_reimbursement import (
    create_claim,
    get_account_claim_summary,
    get_claim,
    get_or_create_policy,
    get_policy,
    list_all_platform,
    list_member_claims,
    mark_claim_paid,
    review_claim,
    submit_claim,
    update_claim,
    update_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-mileage-reimbursement"])


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


def _to_claim_response(claim) -> MileageClaimResponse:
    return MileageClaimResponse.model_validate(claim)


def _to_policy_response(policy) -> MileagePolicyResponse:
    return MileagePolicyResponse.model_validate(policy)


# ---------------------------------------------------------------------------
# Member: view policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/mileage/policy",
    response_model=MileagePolicyResponse,
    summary="Member: view the mileage reimbursement policy for my account",
)
async def get_my_mileage_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the mileage reimbursement policy for the caller's corporate account.

    Creates the policy with default values if it has not been configured yet.
    """
    account_id = await _resolve_account_id(db, user.id)
    policy = await get_or_create_policy(db, account_id, user.id)
    await db.commit()
    return _to_policy_response(policy)


# ---------------------------------------------------------------------------
# Admin: update policy — declared BEFORE member routes to avoid ambiguity
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/mileage/policy",
    response_model=MileagePolicyResponse,
    summary="Admin: update the mileage reimbursement policy for my account",
)
async def update_my_mileage_policy(
    data: MileagePolicyUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the mileage policy.  Only provided fields are changed."""
    account_id = await _resolve_account_id(db, user.id)
    kwargs = {k: v for k, v in data.model_dump().items() if v is not None}
    policy = await update_policy(db, account_id, **kwargs)
    await db.commit()
    return _to_policy_response(policy)


# ---------------------------------------------------------------------------
# Member: create claim (201)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/mileage/claims",
    response_model=MileageClaimResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Member: create a new draft mileage claim",
)
async def create_my_mileage_claim(
    data: MileageClaimCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a draft mileage claim.

    Returns 422 if *miles* exceeds the policy cap.
    """
    account_id = await _resolve_account_id(db, user.id)
    claim = await create_claim(
        db,
        account_id=account_id,
        member_id=user.id,
        trip_date=data.trip_date,
        miles=data.miles,
        description=data.description,
        trip_purpose_id=data.trip_purpose_id,
        cost_center_id=data.cost_center_id,
    )
    await db.commit()
    return _to_claim_response(claim)


# ---------------------------------------------------------------------------
# Admin: list all account claims — declared BEFORE /{claim_id} to avoid collision
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/mileage/claims/all",
    response_model=MileageClaimListResponse,
    summary="Admin: list all mileage claims for my corporate account",
)
async def list_all_account_claims(
    status_filter: Optional[ClaimStatus] = Query(None, alias="status"),
    member_id: Optional[int] = Query(None, description="Filter by member user ID."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all mileage claims for the caller's corporate account."""
    account_id = await _resolve_account_id(db, user.id)
    if member_id is not None:
        claims = await list_member_claims(
            db,
            account_id=account_id,
            member_id=member_id,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
    else:
        claims = await list_all_platform(
            db,
            account_id=account_id,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
    return MileageClaimListResponse(
        total=len(claims),
        items=[_to_claim_response(c) for c in claims],
    )


# ---------------------------------------------------------------------------
# Admin: account summary — declared BEFORE /{claim_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/mileage/claims/summary",
    response_model=MileageClaimSummaryResponse,
    summary="Admin: get mileage claim aggregate summary for my account",
)
async def get_my_account_claim_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate mileage reimbursement statistics for the caller's account."""
    account_id = await _resolve_account_id(db, user.id)
    summary = await get_account_claim_summary(db, account_id=account_id)
    return MileageClaimSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# Member: list my claims
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/mileage/claims",
    response_model=MileageClaimListResponse,
    summary="Member: list my mileage claims",
)
async def list_my_mileage_claims(
    status_filter: Optional[ClaimStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all mileage claims for the calling member, optionally filtered by status."""
    account_id = await _resolve_account_id(db, user.id)
    claims = await list_member_claims(
        db,
        account_id=account_id,
        member_id=user.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return MileageClaimListResponse(
        total=len(claims),
        items=[_to_claim_response(c) for c in claims],
    )


# ---------------------------------------------------------------------------
# Member: get single claim
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/mileage/claims/{claim_id}",
    response_model=MileageClaimResponse,
    summary="Member: get a specific mileage claim",
)
async def get_my_mileage_claim(
    claim_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single mileage claim by id."""
    account_id = await _resolve_account_id(db, user.id)
    claim = await get_claim(db, account_id=account_id, claim_id=claim_id)
    return _to_claim_response(claim)


# ---------------------------------------------------------------------------
# Member: update draft claim
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/mileage/claims/{claim_id}",
    response_model=MileageClaimResponse,
    summary="Member: update a draft mileage claim",
)
async def update_my_mileage_claim(
    claim_id: int,
    data: MileageClaimUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a draft mileage claim.

    Returns 409 if the claim has already been submitted.
    """
    account_id = await _resolve_account_id(db, user.id)
    kwargs = {k: v for k, v in data.model_dump().items() if v is not None}
    claim = await update_claim(db, account_id=account_id, claim_id=claim_id, **kwargs)
    await db.commit()
    return _to_claim_response(claim)


# ---------------------------------------------------------------------------
# Member: submit claim
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/mileage/claims/{claim_id}/submit",
    response_model=MileageClaimResponse,
    summary="Member: submit a draft mileage claim for review",
)
async def submit_my_mileage_claim(
    claim_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a draft claim.

    The claim is auto-approved when both the USD amount and miles are within
    the policy thresholds (or when no thresholds are configured).  Otherwise
    the claim moves to 'submitted' and awaits admin review.

    Returns 409 if the claim is not in draft status.
    Returns 422 if the policy requires a trip purpose and none is set.
    """
    account_id = await _resolve_account_id(db, user.id)
    claim = await submit_claim(
        db, account_id=account_id, claim_id=claim_id, member_id=user.id
    )
    await db.commit()
    return _to_claim_response(claim)


# ---------------------------------------------------------------------------
# Admin: review claim (approve / reject)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/mileage/claims/{claim_id}/review",
    response_model=MileageClaimResponse,
    summary="Admin: approve or reject a submitted mileage claim",
)
async def review_my_account_claim(
    claim_id: int,
    data: MileageClaimReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a submitted mileage claim.

    Returns 409 if the claim is not in submitted status.
    """
    account_id = await _resolve_account_id(db, user.id)
    claim = await review_claim(
        db,
        account_id=account_id,
        claim_id=claim_id,
        reviewer_id=user.id,
        action=data.action,
        note=data.note,
    )
    await db.commit()
    return _to_claim_response(claim)


# ---------------------------------------------------------------------------
# Admin: mark claim paid
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/mileage/claims/{claim_id}/paid",
    response_model=MileageClaimResponse,
    summary="Admin: mark an approved mileage claim as paid",
)
async def mark_my_account_claim_paid(
    claim_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an approved claim as paid.

    Returns 409 if the claim is not in approved status.
    """
    account_id = await _resolve_account_id(db, user.id)
    claim = await mark_claim_paid(
        db,
        account_id=account_id,
        claim_id=claim_id,
        paid_by_id=user.id,
    )
    await db.commit()
    return _to_claim_response(claim)


# ---------------------------------------------------------------------------
# Platform-admin: list claims for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/mileage",
    response_model=MileageClaimListResponse,
    summary="Platform admin: list all mileage claims for a corporate account",
)
async def platform_admin_list_mileage_claims(
    account_id: int,
    status_filter: Optional[ClaimStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all mileage claims for any corporate account (platform admin only)."""
    claims = await list_all_platform(
        db,
        account_id=account_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return MileageClaimListResponse(
        total=len(claims),
        items=[_to_claim_response(c) for c in claims],
    )
