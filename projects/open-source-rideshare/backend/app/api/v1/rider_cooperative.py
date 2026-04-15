"""Rider cooperative membership, voting, and dividend endpoints.

Rider endpoints (authenticated, RIDER role):
  POST /riders/me/cooperative/membership          — apply to join
  GET  /riders/me/cooperative/membership          — get own membership status
  DELETE /riders/me/cooperative/membership        — resign membership
  DELETE /riders/me/cooperative/membership/application — withdraw pending application
  GET  /riders/me/cooperative/proposals           — list open proposals to vote on
  POST /riders/me/cooperative/proposals/{id}/vote — cast a vote
  GET  /riders/me/cooperative/proposals/{id}/tally — rider-side tally
  GET  /riders/me/cooperative/proposals/{id}/my-vote — check own vote
  GET  /riders/me/cooperative/dividends           — list own dividend shares

Admin endpoints (ADMIN role):
  GET  /admin/cooperative/rider-members           — list all rider-members
  POST /admin/cooperative/rider-members/{id}/approve — approve application
  POST /admin/cooperative/rider-members/{id}/suspend — suspend member
  POST /admin/cooperative/rider-members/{id}/reinstate — reinstate suspended member
  GET  /admin/cooperative/rider-summary           — platform stats
  POST /admin/cooperative/rider-dividends         — generate rider shares for a dividend
  GET  /admin/cooperative/rider-dividends/{dividend_id} — list shares for a dividend
  POST /admin/cooperative/rider-dividend-shares/{id}/pay — mark share paid
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User, UserRole
from app.schemas.rider_cooperative import (
    GenerateRiderSharesRequest,
    MembershipApplicationRequest,
    ProposalRiderTallyResponse,
    ProposalSummary,
    ReinstateMemberRequest,
    RiderCoopMembershipListResponse,
    RiderCoopMembershipResponse,
    RiderCoopSummaryResponse,
    RiderDividendShareListResponse,
    RiderDividendShareResponse,
    RiderVoteRequest,
    RiderVoteResponse,
    SuspendMemberRequest,
)
from app.services import rider_cooperative as svc

router = APIRouter(tags=["rider-cooperative"])


def _require_rider(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.RIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for riders only.",
        )
    return user


# ---------------------------------------------------------------------------
# Rider — membership
# ---------------------------------------------------------------------------

@router.post(
    "/riders/me/cooperative/membership",
    response_model=RiderCoopMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply to join the cooperative",
)
async def apply_for_membership(
    _body: MembershipApplicationRequest = MembershipApplicationRequest(),
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    return await svc.apply_for_membership(db, rider)


@router.get(
    "/riders/me/cooperative/membership",
    response_model=RiderCoopMembershipResponse,
    summary="Get own cooperative membership status",
)
async def get_my_membership(
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    membership = await svc.get_membership(db, rider.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cooperative membership found. Apply first.",
        )
    return membership


@router.delete(
    "/riders/me/cooperative/membership",
    response_model=RiderCoopMembershipResponse,
    summary="Resign from the cooperative",
)
async def resign_membership(
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    return await svc.resign_membership(db, rider)


@router.delete(
    "/riders/me/cooperative/membership/application",
    response_model=RiderCoopMembershipResponse,
    summary="Withdraw a pending membership application",
)
async def withdraw_application(
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    return await svc.withdraw_application(db, rider)


# ---------------------------------------------------------------------------
# Rider — voting
# ---------------------------------------------------------------------------

@router.get(
    "/riders/me/cooperative/proposals",
    response_model=list[ProposalSummary],
    summary="List open cooperative proposals available for rider voting",
)
async def list_open_proposals(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    proposals = await svc.list_open_proposals(db, skip=skip, limit=limit)
    return [
        ProposalSummary(
            id=p.id,
            title=p.title,
            description=p.description,
            proposal_type=p.proposal_type,
            status=p.status,
            voting_ends_at=getattr(p, "voting_ends_at", None),
            rider_votes_open=True,
        )
        for p in proposals
    ]


@router.post(
    "/riders/me/cooperative/proposals/{proposal_id}/vote",
    response_model=RiderVoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cast a rider-member vote on a cooperative proposal",
)
async def cast_vote(
    proposal_id: int,
    body: RiderVoteRequest,
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    return await svc.cast_vote(db, rider, proposal_id, body.choice)


@router.get(
    "/riders/me/cooperative/proposals/{proposal_id}/tally",
    response_model=ProposalRiderTallyResponse,
    summary="View rider-side vote tally for a proposal",
)
async def get_proposal_tally(
    proposal_id: int,
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_proposal_tally(db, rider, proposal_id)


@router.get(
    "/riders/me/cooperative/proposals/{proposal_id}/my-vote",
    response_model=RiderVoteResponse | None,
    summary="Check own vote on a proposal",
)
async def get_my_vote(
    proposal_id: int,
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_my_vote(db, rider, proposal_id)


# ---------------------------------------------------------------------------
# Rider — dividends
# ---------------------------------------------------------------------------

@router.get(
    "/riders/me/cooperative/dividends",
    response_model=RiderDividendShareListResponse,
    summary="List own cooperative dividend shares",
)
async def list_my_dividends(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    rider: User = Depends(_require_rider),
    db: AsyncSession = Depends(get_db),
):
    total, items = await svc.list_my_dividends(db, rider, skip=skip, limit=limit)
    return RiderDividendShareListResponse(total=total, items=items)


# ---------------------------------------------------------------------------
# Admin — membership management
# ---------------------------------------------------------------------------

@router.get(
    "/admin/cooperative/rider-members",
    response_model=RiderCoopMembershipListResponse,
    summary="List all rider cooperative members (admin)",
)
async def admin_list_members(
    status_filter: str | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total, items = await svc.list_members(db, status_filter=status_filter, skip=skip, limit=limit)
    return RiderCoopMembershipListResponse(total=total, items=items)


@router.post(
    "/admin/cooperative/rider-members/{membership_id}/approve",
    response_model=RiderCoopMembershipResponse,
    summary="Approve a rider membership application (admin)",
)
async def admin_approve_membership(
    membership_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.approve_membership(db, membership_id, admin)


@router.post(
    "/admin/cooperative/rider-members/{membership_id}/suspend",
    response_model=RiderCoopMembershipResponse,
    summary="Suspend a rider cooperative member (admin)",
)
async def admin_suspend_membership(
    membership_id: int,
    body: SuspendMemberRequest = SuspendMemberRequest(),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.suspend_membership(db, membership_id, admin, reason=body.reason)


@router.post(
    "/admin/cooperative/rider-members/{membership_id}/reinstate",
    response_model=RiderCoopMembershipResponse,
    summary="Reinstate a suspended rider cooperative member (admin)",
)
async def admin_reinstate_membership(
    membership_id: int,
    _body: ReinstateMemberRequest = ReinstateMemberRequest(),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.reinstate_membership(db, membership_id, admin)


@router.get(
    "/admin/cooperative/rider-summary",
    response_model=RiderCoopSummaryResponse,
    summary="Platform-wide rider cooperative stats (admin)",
)
async def admin_get_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    data = await svc.get_summary(db)
    return RiderCoopSummaryResponse(**data)


# ---------------------------------------------------------------------------
# Admin — dividend shares
# ---------------------------------------------------------------------------

@router.post(
    "/admin/cooperative/rider-dividends",
    response_model=list[RiderDividendShareResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate rider dividend shares for an approved cooperative dividend (admin)",
)
async def admin_generate_rider_shares(
    body: GenerateRiderSharesRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.generate_rider_shares(db, body.dividend_id, body.rider_surplus_usd, admin)


@router.get(
    "/admin/cooperative/rider-dividends/{dividend_id}",
    response_model=RiderDividendShareListResponse,
    summary="List rider dividend shares for a specific dividend period (admin)",
)
async def admin_list_dividend_shares(
    dividend_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total, items = await svc.list_dividend_shares(db, dividend_id, skip=skip, limit=limit)
    return RiderDividendShareListResponse(total=total, items=items)


@router.post(
    "/admin/cooperative/rider-dividend-shares/{share_id}/pay",
    response_model=RiderDividendShareResponse,
    summary="Mark a rider dividend share as paid (admin)",
)
async def admin_mark_share_paid(
    share_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.mark_share_paid(db, share_id, admin)
