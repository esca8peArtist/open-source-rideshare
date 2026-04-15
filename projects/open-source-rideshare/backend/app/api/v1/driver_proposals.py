"""Cooperative governance endpoints — driver proposals and voting.

Public endpoints (no auth):
  GET  /cooperative/proposals                   — list open proposals
  GET  /cooperative/proposals/{id}              — proposal detail

Driver endpoints (DRIVER role):
  POST /drivers/me/proposals                    — submit a new proposal (→ draft)
  GET  /drivers/me/proposals                    — list own submitted proposals
  POST /cooperative/proposals/{id}/vote         — cast a vote
  GET  /cooperative/proposals/{id}/my-vote      — check own vote status

Admin endpoints (ADMIN role):
  GET  /admin/cooperative/proposals             — list all proposals (all statuses)
  POST /admin/cooperative/proposals             — create official proposal
  PUT  /admin/cooperative/proposals/{id}        — update title/description/dates
  POST /admin/cooperative/proposals/{id}/open   — open voting (set closing deadline)
  POST /admin/cooperative/proposals/{id}/close  — close voting and compute result
  POST /admin/cooperative/proposals/{id}/withdraw  — withdraw a draft
  POST /admin/cooperative/proposals/{id}/implement — mark passed proposal as enacted
  GET  /admin/cooperative/proposals/{id}/votes  — paginated vote records
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.driver_proposal import DriverProposal, ProposalStatus, VoteChoice
from app.models.user import User
from app.schemas.driver_proposal import (
    AdminCloseResultResponse,
    AdminCreateProposalRequest,
    CastVoteRequest,
    CreateProposalRequest,
    MyVoteResponse,
    ProposalDetail,
    ProposalListResponse,
    ProposalSummary,
    UpdateProposalRequest,
    VoteResponse,
)
from app.services.driver_proposal import (
    admin_close_proposal,
    admin_create_proposal,
    admin_list_proposals,
    admin_mark_implemented,
    admin_open_proposal,
    admin_update_proposal,
    admin_withdraw_proposal,
    cast_vote,
    driver_list_own_proposals,
    driver_submit_proposal,
    get_my_vote,
    get_proposal,
    get_proposal_votes,
    list_open_proposals,
)

router = APIRouter(tags=["cooperative-governance"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_driver_profile(user: User, db: AsyncSession) -> DriverProfile:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile


async def _get_proposal_or_404(proposal_id: int, db: AsyncSession) -> DriverProposal:
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/cooperative/proposals", response_model=ProposalListResponse)
async def list_proposals_public(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all open proposals. No authentication required."""
    proposals, total = await list_open_proposals(db, offset=offset, limit=limit)
    return ProposalListResponse(
        proposals=[ProposalSummary.from_orm_extended(p) for p in proposals],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/cooperative/proposals/{proposal_id}", response_model=ProposalDetail)
async def get_proposal_public(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get detail of an open or closed proposal. Draft/withdrawn are hidden from public."""
    proposal = await _get_proposal_or_404(proposal_id, db)
    if proposal.status in (ProposalStatus.draft, ProposalStatus.withdrawn):
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ProposalDetail.from_orm_extended(proposal)


# ---------------------------------------------------------------------------
# Driver: submit proposals
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/proposals",
    response_model=ProposalDetail,
    status_code=status.HTTP_201_CREATED,
)
async def submit_proposal(
    body: CreateProposalRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver submits a new proposal. Starts as draft — admin reviews before opening."""
    driver = await _get_driver_profile(user, db)
    # Minimum ride threshold to even submit a proposal (10 rides)
    from app.services.driver_proposal import _driver_lifetime_rides
    lifetime = await _driver_lifetime_rides(db, driver.id)
    if lifetime < 10:
        raise HTTPException(
            status_code=400,
            detail="You need at least 10 completed rides to submit a proposal.",
        )
    proposal = await driver_submit_proposal(db, user.id, body)
    await db.commit()
    await db.refresh(proposal)
    return ProposalDetail.from_orm_extended(proposal)


@router.get("/drivers/me/proposals", response_model=ProposalListResponse)
async def list_my_proposals(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """List all proposals submitted by the authenticated driver."""
    proposals = await driver_list_own_proposals(db, user.id)
    return ProposalListResponse(
        proposals=[ProposalSummary.from_orm_extended(p) for p in proposals],
        total=len(proposals),
        offset=0,
        limit=len(proposals),
    )


# ---------------------------------------------------------------------------
# Driver: voting
# ---------------------------------------------------------------------------


@router.post(
    "/cooperative/proposals/{proposal_id}/vote",
    response_model=VoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def vote_on_proposal(
    proposal_id: int,
    body: CastVoteRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Cast a vote on an open proposal. Each driver may vote once."""
    driver = await _get_driver_profile(user, db)
    try:
        vote = await cast_vote(db, proposal_id, driver.id, body.vote)
    except ValueError as exc:
        msg = str(exc)
        if msg == "proposal_not_found":
            raise HTTPException(status_code=404, detail="Proposal not found")
        if msg == "proposal_not_open":
            raise HTTPException(status_code=409, detail="Proposal is not open for voting")
        if msg == "voting_not_started":
            raise HTTPException(status_code=409, detail="Voting has not started yet")
        if msg == "voting_closed":
            raise HTTPException(status_code=409, detail="Voting period has ended")
        if msg == "already_voted":
            raise HTTPException(status_code=409, detail="You have already voted on this proposal")
        if msg.startswith("insufficient_rides:"):
            needed = msg.split(":")[1]
            raise HTTPException(
                status_code=403,
                detail=f"You need at least {needed} completed rides to vote on this proposal",
            )
        raise HTTPException(status_code=400, detail=msg)
    await db.commit()
    await db.refresh(vote)
    return VoteResponse(
        proposal_id=vote.proposal_id,
        vote=vote.vote,
        voted_at=vote.voted_at,
    )


@router.get("/cooperative/proposals/{proposal_id}/my-vote", response_model=MyVoteResponse)
async def my_vote(
    proposal_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's vote status on a proposal."""
    await _get_proposal_or_404(proposal_id, db)
    driver = await _get_driver_profile(user, db)
    vote = await get_my_vote(db, proposal_id, driver.id)
    if vote is None:
        return MyVoteResponse(
            proposal_id=proposal_id,
            voted=False,
            vote=None,
            voted_at=None,
        )
    return MyVoteResponse(
        proposal_id=proposal_id,
        voted=True,
        vote=vote.vote,
        voted_at=vote.voted_at,
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/cooperative/proposals", response_model=ProposalListResponse)
async def admin_list(
    status_filter: ProposalStatus | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all proposals with optional status filter."""
    proposals, total = await admin_list_proposals(
        db, status_filter=status_filter, offset=offset, limit=limit
    )
    return ProposalListResponse(
        proposals=[ProposalSummary.from_orm_extended(p) for p in proposals],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/admin/cooperative/proposals",
    response_model=ProposalDetail,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create(
    body: AdminCreateProposalRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: create an official cooperative proposal."""
    if body.voting_opens_at and body.voting_closes_at:
        if body.voting_closes_at <= body.voting_opens_at:
            raise HTTPException(
                status_code=400,
                detail="voting_closes_at must be after voting_opens_at",
            )
    proposal = await admin_create_proposal(db, user.id, body)
    await db.commit()
    await db.refresh(proposal)
    return ProposalDetail.from_orm_extended(proposal)


@router.get("/admin/cooperative/proposals/{proposal_id}", response_model=ProposalDetail)
async def admin_get(
    proposal_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: get any proposal by ID regardless of status."""
    proposal = await _get_proposal_or_404(proposal_id, db)
    return ProposalDetail.from_orm_extended(proposal)


@router.put("/admin/cooperative/proposals/{proposal_id}", response_model=ProposalDetail)
async def admin_update(
    proposal_id: int,
    body: UpdateProposalRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update proposal title/description/voting dates."""
    try:
        proposal = await admin_update_proposal(db, proposal_id, body)
    except ValueError as exc:
        msg = str(exc)
        if msg == "proposal_not_found":
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=409, detail="Cannot update a terminal proposal")
    await db.commit()
    await db.refresh(proposal)
    return ProposalDetail.from_orm_extended(proposal)


@router.post("/admin/cooperative/proposals/{proposal_id}/open", response_model=ProposalDetail)
async def admin_open(
    proposal_id: int,
    voting_closes_at: datetime = Query(...),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: open a draft proposal for voting, setting the deadline."""
    now = datetime.now(timezone.utc)
    if voting_closes_at <= now:
        raise HTTPException(status_code=400, detail="voting_closes_at must be in the future")
    try:
        proposal = await admin_open_proposal(db, proposal_id, voting_closes_at)
    except ValueError as exc:
        msg = str(exc)
        if msg == "proposal_not_found":
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=409, detail="Proposal cannot be opened from its current state")
    await db.commit()
    await db.refresh(proposal)
    return ProposalDetail.from_orm_extended(proposal)


@router.post(
    "/admin/cooperative/proposals/{proposal_id}/close",
    response_model=AdminCloseResultResponse,
)
async def admin_close(
    proposal_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: close voting and compute final result (passed or failed)."""
    try:
        proposal = await admin_close_proposal(db, proposal_id)
    except ValueError as exc:
        msg = str(exc)
        if msg == "proposal_not_found":
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=409, detail="Proposal is not open")
    await db.commit()
    await db.refresh(proposal)
    decisive = proposal.votes_for + proposal.votes_against
    yes_pct = round(proposal.votes_for / decisive * 100, 1) if decisive > 0 else None
    return AdminCloseResultResponse(
        proposal_id=proposal.id,
        status=proposal.status,
        votes_for=proposal.votes_for,
        votes_against=proposal.votes_against,
        votes_abstain=proposal.votes_abstain,
        yes_pct=yes_pct,
        passed=proposal.status == ProposalStatus.passed,
        threshold_required_pct=float(proposal.result_threshold_pct) * 100,
    )


@router.post("/admin/cooperative/proposals/{proposal_id}/withdraw", response_model=ProposalDetail)
async def admin_withdraw(
    proposal_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: withdraw a draft proposal (before voting opens)."""
    try:
        proposal = await admin_withdraw_proposal(db, proposal_id)
    except ValueError as exc:
        msg = str(exc)
        if msg == "proposal_not_found":
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=409, detail="Only draft proposals can be withdrawn")
    await db.commit()
    await db.refresh(proposal)
    return ProposalDetail.from_orm_extended(proposal)


@router.post("/admin/cooperative/proposals/{proposal_id}/implement", response_model=ProposalDetail)
async def admin_implement(
    proposal_id: int,
    implementation_notes: str | None = Query(None),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: mark a passed proposal as implemented (enacted on the platform)."""
    try:
        proposal = await admin_mark_implemented(db, proposal_id, implementation_notes)
    except ValueError as exc:
        msg = str(exc)
        if msg == "proposal_not_found":
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=409, detail="Only passed proposals can be marked as implemented")
    await db.commit()
    await db.refresh(proposal)
    return ProposalDetail.from_orm_extended(proposal)


@router.get("/admin/cooperative/proposals/{proposal_id}/votes")
async def admin_vote_records(
    proposal_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: paginated individual vote records for a proposal."""
    await _get_proposal_or_404(proposal_id, db)
    votes = await get_proposal_votes(db, proposal_id, offset=offset, limit=limit)
    return {
        "proposal_id": proposal_id,
        "votes": [
            {
                "driver_profile_id": v.driver_profile_id,
                "vote": v.vote,
                "voted_at": v.voted_at,
            }
            for v in votes
        ],
        "count": len(votes),
        "offset": offset,
        "limit": limit,
    }
