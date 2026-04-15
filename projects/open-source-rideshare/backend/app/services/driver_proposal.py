"""Cooperative governance service layer — driver proposals and voting.

Business rules:
- Proposals start as draft. Admin can open immediately or schedule a window.
- Drivers can submit proposals (status=draft initially, admin reviews before opening).
- Voting requires: proposal is open, now is within [voting_opens_at, voting_closes_at],
  and driver has >= min_lifetime_rides_to_vote completed rides.
- Each driver may vote once per proposal (unique constraint enforced at DB level).
  Changing a vote is not allowed — vote is final.
- On close: if (votes_for / (votes_for + votes_against)) >= result_threshold_pct
  the proposal passes; otherwise it fails. Abstentions don't count toward the ratio.
- Implemented proposals are immutable — admin marks them as enacted separately.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_proposal import (
    DriverProposal,
    DriverVote,
    ProposalStatus,
    VoteChoice,
)
from app.models.ride import Ride, RideStatus
from app.schemas.driver_proposal import (
    AdminCreateProposalRequest,
    CreateProposalRequest,
    UpdateProposalRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _driver_lifetime_rides(db: AsyncSession, driver_profile_id: int) -> int:
    """Return the count of completed rides for a driver."""
    stmt = (
        select(func.count())
        .select_from(Ride)
        .where(
            Ride.driver_id == driver_profile_id,
            Ride.status == RideStatus.COMPLETED,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one() or 0


def _compute_result(proposal: DriverProposal) -> ProposalStatus:
    """Return passed or failed based on vote counts and threshold."""
    decisive = proposal.votes_for + proposal.votes_against
    if decisive == 0:
        return ProposalStatus.failed  # no decisive votes → fails
    yes_pct = proposal.votes_for / decisive
    if yes_pct >= float(proposal.result_threshold_pct):
        return ProposalStatus.passed
    return ProposalStatus.failed


# ---------------------------------------------------------------------------
# Public reads
# ---------------------------------------------------------------------------


async def list_open_proposals(
    db: AsyncSession,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[DriverProposal], int]:
    """Return paginated list of open proposals (public — no auth required)."""
    count_stmt = (
        select(func.count())
        .select_from(DriverProposal)
        .where(DriverProposal.status == ProposalStatus.open)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(DriverProposal)
        .where(DriverProposal.status == ProposalStatus.open)
        .order_by(DriverProposal.voting_closes_at.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def get_proposal(db: AsyncSession, proposal_id: int) -> DriverProposal | None:
    """Fetch a single proposal by ID (any status — caller filters for public)."""
    stmt = select(DriverProposal).where(DriverProposal.id == proposal_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Driver operations
# ---------------------------------------------------------------------------


async def driver_submit_proposal(
    db: AsyncSession,
    user_id: int,
    data: CreateProposalRequest,
) -> DriverProposal:
    """Driver submits a new proposal (starts as draft, needs admin to open)."""
    proposal = DriverProposal(
        title=data.title,
        description=data.description,
        proposal_type=data.proposal_type,
        min_lifetime_rides_to_vote=data.min_lifetime_rides_to_vote,
        result_threshold_pct=data.result_threshold_pct,
        created_by_user_id=user_id,
        created_by_admin=False,
        status=ProposalStatus.draft,
    )
    db.add(proposal)
    await db.flush()
    return proposal


async def driver_list_own_proposals(
    db: AsyncSession,
    user_id: int,
) -> list[DriverProposal]:
    """Return all proposals submitted by a specific user."""
    stmt = (
        select(DriverProposal)
        .where(DriverProposal.created_by_user_id == user_id)
        .order_by(DriverProposal.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def cast_vote(
    db: AsyncSession,
    proposal_id: int,
    driver_profile_id: int,
    vote_choice: VoteChoice,
) -> DriverVote:
    """Cast a vote on an open proposal.

    Raises ValueError for:
    - proposal not found
    - proposal not open
    - voting window not active
    - driver already voted
    - driver ineligible (not enough rides)
    """
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("proposal_not_found")

    if proposal.status != ProposalStatus.open:
        raise ValueError("proposal_not_open")

    now = datetime.now(timezone.utc)
    if proposal.voting_opens_at and now < proposal.voting_opens_at:
        raise ValueError("voting_not_started")
    if proposal.voting_closes_at and now > proposal.voting_closes_at:
        raise ValueError("voting_closed")

    # Check eligibility
    lifetime_rides = await _driver_lifetime_rides(db, driver_profile_id)
    if lifetime_rides < proposal.min_lifetime_rides_to_vote:
        raise ValueError(
            f"insufficient_rides:{proposal.min_lifetime_rides_to_vote}"
        )

    # Check for duplicate vote (also enforced by DB unique constraint)
    existing_stmt = select(DriverVote).where(
        DriverVote.proposal_id == proposal_id,
        DriverVote.driver_profile_id == driver_profile_id,
    )
    if (await db.execute(existing_stmt)).scalar_one_or_none() is not None:
        raise ValueError("already_voted")

    vote = DriverVote(
        proposal_id=proposal_id,
        driver_profile_id=driver_profile_id,
        vote=vote_choice,
    )
    db.add(vote)

    # Update cached tallies
    if vote_choice == VoteChoice.yes:
        proposal.votes_for += 1
    elif vote_choice == VoteChoice.no:
        proposal.votes_against += 1
    else:
        proposal.votes_abstain += 1

    await db.flush()
    return vote


async def get_my_vote(
    db: AsyncSession,
    proposal_id: int,
    driver_profile_id: int,
) -> DriverVote | None:
    """Return this driver's vote record for a proposal, or None."""
    stmt = select(DriverVote).where(
        DriverVote.proposal_id == proposal_id,
        DriverVote.driver_profile_id == driver_profile_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------


async def admin_create_proposal(
    db: AsyncSession,
    user_id: int,
    data: AdminCreateProposalRequest,
) -> DriverProposal:
    """Admin creates a proposal, optionally opening it immediately."""
    status = ProposalStatus.open if data.open_immediately else ProposalStatus.draft
    proposal = DriverProposal(
        title=data.title,
        description=data.description,
        proposal_type=data.proposal_type,
        min_lifetime_rides_to_vote=data.min_lifetime_rides_to_vote,
        result_threshold_pct=data.result_threshold_pct,
        created_by_user_id=user_id,
        created_by_admin=True,
        status=status,
        voting_opens_at=data.voting_opens_at,
        voting_closes_at=data.voting_closes_at,
    )
    db.add(proposal)
    await db.flush()
    return proposal


async def admin_list_proposals(
    db: AsyncSession,
    status_filter: ProposalStatus | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[DriverProposal], int]:
    """Admin list — all statuses by default, filterable."""
    base = select(DriverProposal)
    count_base = select(func.count()).select_from(DriverProposal)
    if status_filter is not None:
        base = base.where(DriverProposal.status == status_filter)
        count_base = count_base.where(DriverProposal.status == status_filter)

    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(DriverProposal.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return list(rows), total


async def admin_update_proposal(
    db: AsyncSession,
    proposal_id: int,
    data: UpdateProposalRequest,
) -> DriverProposal:
    """Update mutable fields of a proposal.

    Does not change status — use open/close/implement endpoints for that.
    Raises ValueError if proposal not found or is in a terminal state.
    """
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("proposal_not_found")
    if proposal.status in (
        ProposalStatus.passed,
        ProposalStatus.failed,
        ProposalStatus.implemented,
    ):
        raise ValueError("proposal_terminal")

    if data.title is not None:
        proposal.title = data.title
    if data.description is not None:
        proposal.description = data.description
    if data.implementation_notes is not None:
        proposal.implementation_notes = data.implementation_notes
    if data.voting_opens_at is not None:
        proposal.voting_opens_at = data.voting_opens_at
    if data.voting_closes_at is not None:
        proposal.voting_closes_at = data.voting_closes_at

    await db.flush()
    return proposal


async def admin_open_proposal(
    db: AsyncSession,
    proposal_id: int,
    voting_closes_at: datetime,
) -> DriverProposal:
    """Transition a draft proposal to open, setting the voting deadline.

    Raises ValueError if not found or not in draft/withdrawn state.
    """
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("proposal_not_found")
    if proposal.status not in (ProposalStatus.draft, ProposalStatus.withdrawn):
        raise ValueError("cannot_open")

    now = datetime.now(timezone.utc)
    proposal.status = ProposalStatus.open
    proposal.voting_opens_at = now
    proposal.voting_closes_at = voting_closes_at
    await db.flush()
    return proposal


async def admin_close_proposal(
    db: AsyncSession,
    proposal_id: int,
) -> DriverProposal:
    """Close an open proposal and compute the result (passed or failed)."""
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("proposal_not_found")
    if proposal.status != ProposalStatus.open:
        raise ValueError("proposal_not_open")

    proposal.status = _compute_result(proposal)
    await db.flush()
    return proposal


async def admin_withdraw_proposal(
    db: AsyncSession,
    proposal_id: int,
) -> DriverProposal:
    """Withdraw a draft proposal before voting opens."""
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("proposal_not_found")
    if proposal.status != ProposalStatus.draft:
        raise ValueError("can_only_withdraw_draft")
    proposal.status = ProposalStatus.withdrawn
    await db.flush()
    return proposal


async def admin_mark_implemented(
    db: AsyncSession,
    proposal_id: int,
    implementation_notes: str | None,
) -> DriverProposal:
    """Mark a passed proposal as implemented."""
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("proposal_not_found")
    if proposal.status != ProposalStatus.passed:
        raise ValueError("only_passed_proposals_can_be_implemented")

    proposal.status = ProposalStatus.implemented
    proposal.implemented_at = datetime.now(timezone.utc)
    if implementation_notes is not None:
        proposal.implementation_notes = implementation_notes
    await db.flush()
    return proposal


async def get_proposal_votes(
    db: AsyncSession,
    proposal_id: int,
    offset: int = 0,
    limit: int = 100,
) -> list[DriverVote]:
    """Admin access to individual vote records for a proposal."""
    stmt = (
        select(DriverVote)
        .where(DriverVote.proposal_id == proposal_id)
        .order_by(DriverVote.voted_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
