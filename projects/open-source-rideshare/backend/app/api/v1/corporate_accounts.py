"""Corporate / business account API endpoints.

Admin routes  (/api/v1/corporate-accounts/admin/...)
  POST   /admin                            — create corporate account
  GET    /admin                            — list accounts (?active_only=true)
  GET    /admin/{id}                       — account detail (member count, total rides, month spend)
  PATCH  /admin/{id}                       — update account fields
  POST   /admin/{id}/members              — invite user to account
  DELETE /admin/{id}/members/{user_id}    — remove member (status → REMOVED)
  GET    /admin/{id}/members              — list members with status
  GET    /admin/{id}/rides                — paginated list of corporate rides
  GET    /admin/{id}/spend-summary        — spend by month (last 12 months)

Rider routes  (/api/v1/corporate-accounts/riders/...)
  GET    /riders/me/memberships                           — list my memberships
  POST   /riders/me/memberships/{membership_id}/activate  — accept a pending invite
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_account import CorporateAccount, CorporateMembership
from app.models.ride import Ride
from app.models.user import User
from app.schemas.corporate_account import (
    CorporateAccountCreateRequest,
    CorporateAccountDetailResponse,
    CorporateAccountResponse,
    CorporateAccountUpdateRequest,
    CorporateMembershipResponse,
    CorporateRideItem,
    CorporateRideListResponse,
    InviteMemberRequest,
    SpendSummaryResponse,
    MonthlySpendItem,
)
from app.services.corporate_accounts import (
    DEFAULT_PAGE_SIZE,
    activate_membership,
    create_account,
    get_account,
    get_spend_summary,
    invite_member,
    list_account_rides,
    list_accounts,
    list_members,
    list_rider_memberships,
    remove_member,
    update_account,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/corporate-accounts",
    tags=["corporate-accounts"],
)


# ---------------------------------------------------------------------------
# Admin: account management
# ---------------------------------------------------------------------------


@router.post(
    "/admin",
    response_model=CorporateAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a corporate account",
)
async def create_corporate_account(
    req: CorporateAccountCreateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new corporate/business billing account.

    - **company_name**: Display name for the organisation (max 200 chars).
    - **billing_email**: Contact for invoices and billing correspondence.
    - **monthly_limit**: Optional cap on total company spend per calendar month.
    - **per_ride_limit**: Optional cap on a single ride charged to this account.
    """
    account = await create_account(
        db,
        company_name=req.company_name,
        billing_email=req.billing_email,
        monthly_limit=req.monthly_limit,
        per_ride_limit=req.per_ride_limit,
    )
    return CorporateAccountResponse.model_validate(account)


@router.get(
    "/admin",
    response_model=list[CorporateAccountResponse],
    summary="Admin: list corporate accounts",
)
async def list_corporate_accounts(
    active_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of corporate accounts.

    Pass **?active_only=true** to filter to only currently active accounts.
    """
    items, _total = await list_accounts(
        db, active_only=active_only, page=page, page_size=page_size
    )
    return [CorporateAccountResponse.model_validate(a) for a in items]


@router.get(
    "/admin/{account_id}",
    response_model=CorporateAccountDetailResponse,
    summary="Admin: get corporate account detail",
)
async def get_corporate_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return full detail for a single corporate account, including member count
    and total corporate ride count.
    """
    account = await get_account(db, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )

    member_count_result = await db.execute(
        select(func.count()).where(
            CorporateMembership.account_id == account_id
        )
    )
    member_count = member_count_result.scalar_one()

    ride_count_result = await db.execute(
        select(func.count()).where(
            Ride.corporate_account_id == account_id
        )
    )
    total_rides = ride_count_result.scalar_one()

    resp = CorporateAccountDetailResponse.model_validate(account)
    resp.member_count = member_count
    resp.total_rides = total_rides
    return resp


@router.patch(
    "/admin/{account_id}",
    response_model=CorporateAccountResponse,
    summary="Admin: update a corporate account",
)
async def update_corporate_account(
    account_id: int,
    req: CorporateAccountUpdateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a corporate account.

    Only provided fields are changed; omitted fields retain their current values.
    """
    account = await update_account(
        db,
        account_id,
        company_name=req.company_name,
        billing_email=req.billing_email,
        monthly_limit=req.monthly_limit,
        per_ride_limit=req.per_ride_limit,
        is_active=req.is_active,
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )
    return CorporateAccountResponse.model_validate(account)


# ---------------------------------------------------------------------------
# Admin: member management
# ---------------------------------------------------------------------------


@router.post(
    "/admin/{account_id}/members",
    response_model=CorporateMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: invite a user to a corporate account",
)
async def invite_corporate_member(
    account_id: int,
    req: InviteMemberRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send an invitation to a platform user to join a corporate account.

    The invitation starts as **pending**.  The user must call the
    ``/riders/me/memberships/{id}/activate`` endpoint to accept.
    """
    account = await get_account(db, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )

    membership, err = await invite_member(
        db, account_id, req.user_id, req.monthly_limit
    )
    if err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err)
    return CorporateMembershipResponse.model_validate(membership)


@router.delete(
    "/admin/{account_id}/members/{user_id}",
    response_model=CorporateMembershipResponse,
    summary="Admin: remove a member from a corporate account",
)
async def remove_corporate_member(
    account_id: int,
    user_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from a corporate account (sets status to **removed**).

    Removed members can no longer charge rides to this account.
    """
    membership, err = await remove_member(db, account_id, user_id)
    if err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=err,
        )
    return CorporateMembershipResponse.model_validate(membership)


@router.get(
    "/admin/{account_id}/members",
    response_model=list[CorporateMembershipResponse],
    summary="Admin: list members of a corporate account",
)
async def list_corporate_members(
    account_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all memberships for a corporate account, across all statuses."""
    account = await get_account(db, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )

    items, _total = await list_members(db, account_id, page=page, page_size=page_size)
    return [CorporateMembershipResponse.model_validate(m) for m in items]


# ---------------------------------------------------------------------------
# Admin: ride listing and spend summary
# ---------------------------------------------------------------------------


@router.get(
    "/admin/{account_id}/rides",
    response_model=CorporateRideListResponse,
    summary="Admin: list rides billed to a corporate account",
)
async def list_corporate_account_rides(
    account_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of rides that were billed to the given corporate
    account, ordered newest first.
    """
    account = await get_account(db, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )

    rides, total = await list_account_rides(db, account_id, page=page, page_size=page_size)
    return CorporateRideListResponse(
        items=[CorporateRideItem.model_validate(r) for r in rides],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/admin/{account_id}/spend-summary",
    response_model=SpendSummaryResponse,
    summary="Admin: monthly spend summary for a corporate account",
)
async def get_corporate_spend_summary(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the spend breakdown by calendar month (last 12 months) plus the
    current-month running total from the account record.
    """
    account = await get_account(db, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )

    summary = await get_spend_summary(db, account_id)
    return SpendSummaryResponse(
        account_id=summary["account_id"],
        current_month=summary["current_month"],
        current_month_spend=summary["current_month_spend"],
        monthly_breakdown=[
            MonthlySpendItem(month=item["month"], total=item["total"])
            for item in summary["monthly_breakdown"]
        ],
    )


# ---------------------------------------------------------------------------
# Rider: membership management
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/memberships",
    response_model=list[CorporateMembershipResponse],
    summary="Rider: list my corporate memberships",
)
async def list_my_corporate_memberships(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all PENDING and ACTIVE corporate memberships for the authenticated
    rider.  Use this to find pending invitations that can be accepted.
    """
    memberships = await list_rider_memberships(db, user.id)
    return [CorporateMembershipResponse.model_validate(m) for m in memberships]


@router.post(
    "/riders/me/memberships/{membership_id}/activate",
    response_model=CorporateMembershipResponse,
    summary="Rider: accept a corporate membership invitation",
)
async def activate_corporate_membership(
    membership_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a pending corporate account invitation.

    Only the invited user may activate their own membership.  The status
    transitions from **pending** to **active**, enabling corporate billing
    for future rides.
    """
    membership, err = await activate_membership(db, membership_id, user.id)
    if err:
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in err.lower()
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=err)
    return CorporateMembershipResponse.model_validate(membership)
