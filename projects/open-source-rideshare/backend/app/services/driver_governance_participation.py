"""Driver governance participation report service.

Aggregates a driver-member's full cooperative governance history:
proposals submitted and voted on, board elections participated in or run for,
and what is currently open for their engagement.

A cooperative platform is owned and governed by its drivers.  Surfacing
governance participation data is a core obligation of any cooperative —
member-owners have a right to know their own civic engagement record and
what decisions are currently pending their input.

Public API:
    get_driver_governance_participation(db, user_id) → DriverGovernanceParticipation
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_election import (
    BoardCandidacy,
    BoardElection,
    BoardElectionVote,
    CandidacyStatus,
    CooperativeBoardSeat,
    ElectionStatus,
)
from app.models.driver import DriverProfile
from app.models.driver_proposal import (
    DriverProposal,
    DriverVote,
    ProposalStatus,
    VoteChoice,
)
from app.schemas.driver_governance_participation import (
    DriverGovernanceParticipation,
    OpenElectionSummary,
    OpenProposalSummary,
    VoteBreakdown,
)

logger = logging.getLogger(__name__)

# Statuses that count as "eligible to vote" for the participation rate
_VOTEABLE_STATUSES = frozenset(
    {
        ProposalStatus.open,
        ProposalStatus.closed,
        ProposalStatus.passed,
        ProposalStatus.failed,
        ProposalStatus.implemented,
    }
)

# Election statuses where a driver can still take action
_ACTIVE_ELECTION_STATUSES = frozenset(
    {
        ElectionStatus.nominations_open,
        ElectionStatus.voting_open,
    }
)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers — fetch driver profile
# ---------------------------------------------------------------------------


async def _get_driver_profile(db: AsyncSession, user_id: int) -> Optional[DriverProfile]:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Proposals submitted by the driver
# ---------------------------------------------------------------------------


async def _count_submitted_proposals(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """Return (total_submitted, total_submitted_passed)."""
    result = await db.execute(
        select(DriverProposal.status).where(
            DriverProposal.created_by_user_id == user_id
        )
    )
    rows = result.scalars().all()
    total = len(rows)
    passed = sum(
        1
        for s in rows
        if s in (ProposalStatus.passed, ProposalStatus.implemented)
    )
    return total, passed


# ---------------------------------------------------------------------------
# Proposal votes cast by the driver
# ---------------------------------------------------------------------------


async def _fetch_driver_votes(
    db: AsyncSession, driver_profile_id: int
) -> list[DriverVote]:
    result = await db.execute(
        select(DriverVote).where(
            DriverVote.driver_profile_id == driver_profile_id
        )
    )
    return list(result.scalars().all())


async def _count_eligible_proposals(
    db: AsyncSession, lifetime_rides: int
) -> int:
    """Count proposals the driver is eligible to vote on (current ride count).

    Approximation: uses the driver's current lifetime ride count rather than
    historical count at each proposal's open date.  Eligible statuses exclude
    draft and withdrawn (never opened to a vote).
    """
    result = await db.execute(
        select(func.count(DriverProposal.id)).where(
            and_(
                DriverProposal.status.in_(list(_VOTEABLE_STATUSES)),
                DriverProposal.min_lifetime_rides_to_vote <= lifetime_rides,
            )
        )
    )
    count = result.scalar_one()
    return int(count) if count else 0


# ---------------------------------------------------------------------------
# Open proposals the driver hasn't voted on yet
# ---------------------------------------------------------------------------


async def _fetch_open_proposals_awaiting_vote(
    db: AsyncSession,
    driver_profile_id: int,
    lifetime_rides: int,
) -> list[OpenProposalSummary]:
    """Return open proposals the driver is eligible to vote on but hasn't yet."""
    # Proposals already voted on by this driver
    voted_result = await db.execute(
        select(DriverVote.proposal_id).where(
            DriverVote.driver_profile_id == driver_profile_id
        )
    )
    already_voted_ids: set[int] = {row[0] for row in voted_result}

    # All open proposals the driver is eligible for
    open_result = await db.execute(
        select(DriverProposal).where(
            and_(
                DriverProposal.status == ProposalStatus.open,
                DriverProposal.min_lifetime_rides_to_vote <= lifetime_rides,
            )
        ).order_by(DriverProposal.voting_closes_at.asc().nulls_last())
    )
    open_proposals = list(open_result.scalars().all())

    summaries: list[OpenProposalSummary] = []
    for p in open_proposals:
        if p.id in already_voted_ids:
            continue
        summaries.append(
            OpenProposalSummary(
                proposal_id=p.id,
                title=p.title,
                proposal_type=p.proposal_type.value,
                voting_closes_at=p.voting_closes_at,
                votes_for=p.votes_for,
                votes_against=p.votes_against,
                votes_abstain=p.votes_abstain,
            )
        )
    return summaries


# ---------------------------------------------------------------------------
# Board elections
# ---------------------------------------------------------------------------


async def _board_election_stats(
    db: AsyncSession, driver_profile_id: int
) -> tuple[int, int, int]:
    """Return (elections_participated, elections_ran, elections_won)."""
    # Elections participated (cast a ballot)
    vote_result = await db.execute(
        select(func.count(BoardElectionVote.id)).where(
            BoardElectionVote.voter_driver_profile_id == driver_profile_id
        )
    )
    participated = int(vote_result.scalar_one() or 0)

    # Elections the driver ran in (any candidacy status)
    ran_result = await db.execute(
        select(func.count(BoardCandidacy.id)).where(
            BoardCandidacy.driver_profile_id == driver_profile_id
        )
    )
    ran = int(ran_result.scalar_one() or 0)

    # Elections won (driver is the certified winner)
    won_result = await db.execute(
        select(func.count(BoardElection.id)).where(
            BoardElection.winner_id == driver_profile_id
        )
    )
    won = int(won_result.scalar_one() or 0)

    return participated, ran, won


async def _fetch_active_elections(
    db: AsyncSession, driver_profile_id: int
) -> list[OpenElectionSummary]:
    """Return board elections currently in nominations_open or voting_open state."""
    election_result = await db.execute(
        select(BoardElection).where(
            BoardElection.status.in_(list(_ACTIVE_ELECTION_STATUSES))
        ).order_by(BoardElection.voting_closes_at.asc().nulls_last())
    )
    elections = list(election_result.scalars().all())

    if not elections:
        return []

    election_ids = [e.id for e in elections]

    # Check which elections the driver has an approved candidacy in
    cand_result = await db.execute(
        select(BoardCandidacy.election_id).where(
            and_(
                BoardCandidacy.driver_profile_id == driver_profile_id,
                BoardCandidacy.election_id.in_(election_ids),
                BoardCandidacy.status == CandidacyStatus.approved,
            )
        )
    )
    approved_candidacy_election_ids: set[int] = {row[0] for row in cand_result}

    # Check which elections the driver has already voted in
    voted_result = await db.execute(
        select(BoardElectionVote.election_id).where(
            and_(
                BoardElectionVote.voter_driver_profile_id == driver_profile_id,
                BoardElectionVote.election_id.in_(election_ids),
            )
        )
    )
    voted_election_ids: set[int] = {row[0] for row in voted_result}

    # Fetch seat names
    seat_ids = [e.seat_id for e in elections]
    seat_result = await db.execute(
        select(CooperativeBoardSeat).where(CooperativeBoardSeat.id.in_(seat_ids))
    )
    seats_by_id: dict[int, CooperativeBoardSeat] = {
        s.id: s for s in seat_result.scalars().all()
    }

    summaries: list[OpenElectionSummary] = []
    for e in elections:
        seat = seats_by_id.get(e.seat_id)
        seat_name = seat.name if seat else f"Seat #{e.seat_id}"
        summaries.append(
            OpenElectionSummary(
                election_id=e.id,
                title=e.title,
                seat_name=seat_name,
                status=e.status.value,
                nominations_close_at=e.nominations_close_at,
                voting_closes_at=e.voting_closes_at,
                driver_is_candidate=e.id in approved_candidacy_election_ids,
                driver_has_voted=e.id in voted_election_ids,
            )
        )
    return summaries


# ---------------------------------------------------------------------------
# Engagement tier and participation note
# ---------------------------------------------------------------------------


def _engagement_tier(
    total_votes_cast: int,
    proposals_eligible: int,
    participation_rate_pct: Optional[float],
    lifetime_rides: int,
) -> str:
    if total_votes_cast == 0:
        if lifetime_rides < 50:
            return "new"
        if proposals_eligible == 0:
            return "new"
        return "eligible_not_participating"
    if proposals_eligible == 0:
        return "occasional"
    if participation_rate_pct is None:
        return "occasional"
    if participation_rate_pct >= 75.0:
        return "active"
    if participation_rate_pct >= 50.0:
        return "engaged"
    return "occasional"


def _participation_note(
    tier: str,
    total_votes_cast: int,
    proposals_submitted: int,
    board_elections_participated: int,
    open_awaiting: int,
) -> str:
    base = {
        "active": "You are an active cooperative member — you've voted on most eligible proposals.",
        "engaged": "You are an engaged cooperative member — you participate in most governance decisions.",
        "occasional": "You participate occasionally in cooperative governance.",
        "new": "You're a new member — your governance rights unlock as you complete more rides.",
        "eligible_not_participating": (
            "You're eligible to vote on cooperative proposals but haven't cast any votes yet."
        ),
    }.get(tier, "Your governance participation is on record.")

    addendum_parts: list[str] = []
    if proposals_submitted > 0:
        noun = "proposal" if proposals_submitted == 1 else "proposals"
        addendum_parts.append(f"You've submitted {proposals_submitted} {noun}")
    if board_elections_participated > 0:
        noun = "board election" if board_elections_participated == 1 else "board elections"
        addendum_parts.append(f"participated in {board_elections_participated} {noun}")
    if open_awaiting > 0:
        noun = "proposal" if open_awaiting == 1 else "proposals"
        addendum_parts.append(f"{open_awaiting} open {noun} await your vote")

    if addendum_parts:
        return f"{base} {'; '.join(addendum_parts)}."
    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_driver_governance_participation(
    db: AsyncSession,
    user_id: int,
) -> DriverGovernanceParticipation:
    """Compute a full governance participation report for user_id.

    Args:
        db:       Async database session.
        user_id:  Authenticated driver's User.id.

    Returns:
        DriverGovernanceParticipation with full civic engagement history.
    """
    now = _utc_now()

    # Get driver profile for lifetime rides and profile ID
    profile = await _get_driver_profile(db, user_id)
    driver_profile_id: Optional[int] = profile.id if profile else None
    lifetime_rides: int = profile.total_trips if profile else 0

    # Proposals submitted
    proposals_submitted, proposals_submitted_passed = (
        await _count_submitted_proposals(db, user_id)
    )

    # Votes cast on proposals
    if driver_profile_id is not None:
        votes_cast = await _fetch_driver_votes(db, driver_profile_id)
    else:
        votes_cast = []

    total_votes_cast = len(votes_cast)
    vote_breakdown = VoteBreakdown(
        yes=sum(1 for v in votes_cast if v.vote == VoteChoice.yes),
        no=sum(1 for v in votes_cast if v.vote == VoteChoice.no),
        abstain=sum(1 for v in votes_cast if v.vote == VoteChoice.abstain),
    )

    # Eligible proposals (current ride count as approximation)
    proposals_eligible = await _count_eligible_proposals(db, lifetime_rides)

    participation_rate_pct: Optional[float] = None
    if proposals_eligible > 0:
        participation_rate_pct = round(total_votes_cast / proposals_eligible * 100, 1)

    # Open proposals awaiting the driver's vote
    if driver_profile_id is not None:
        open_awaiting = await _fetch_open_proposals_awaiting_vote(
            db, driver_profile_id, lifetime_rides
        )
    else:
        open_awaiting = []

    # Board election stats
    if driver_profile_id is not None:
        board_participated, board_ran, board_won = await _board_election_stats(
            db, driver_profile_id
        )
        active_elections = await _fetch_active_elections(db, driver_profile_id)
    else:
        board_participated, board_ran, board_won = 0, 0, 0
        active_elections = []

    # Engagement tier and note
    tier = _engagement_tier(
        total_votes_cast, proposals_eligible, participation_rate_pct, lifetime_rides
    )
    note = _participation_note(
        tier,
        total_votes_cast,
        proposals_submitted,
        board_participated,
        len(open_awaiting),
    )

    return DriverGovernanceParticipation(
        proposals_submitted=proposals_submitted,
        proposals_submitted_passed=proposals_submitted_passed,
        total_votes_cast=total_votes_cast,
        vote_breakdown=vote_breakdown,
        proposals_eligible=proposals_eligible,
        participation_rate_pct=participation_rate_pct,
        board_elections_participated=board_participated,
        board_elections_ran=board_ran,
        board_elections_won=board_won,
        engagement_tier=tier,
        open_proposals_awaiting_vote=open_awaiting,
        active_elections=active_elections,
        participation_note=note,
        report_generated_at=now,
    )
