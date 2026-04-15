"""Service layer for Cooperative Board Elections.

Business rules:
  - One active election (nominations_open → voting_open) per seat at a time
  - Drivers need >= seat.min_lifetime_rides_to_run to apply for candidacy
  - Drivers need >= election.min_lifetime_rides_to_vote to cast a ballot
  - Voting is secret: individual choices are never exposed via driver endpoints
  - Tallying counts approved candidacy votes only; sets winner to candidacy
    with the most votes (ties broken by earliest applied_at)
  - Certifying sets the current_holder on the seat and sets holder_term_ends_at
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from fastapi import HTTPException
from sqlalchemy import select
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


class BoardElectionError(HTTPException):
    """Convenience wrapper so callers get typed HTTP errors."""


# ---------------------------------------------------------------------------
# Board Seat operations
# ---------------------------------------------------------------------------


async def create_seat(
    db: AsyncSession,
    name: str,
    description: str | None,
    term_months: int,
    max_consecutive_terms: int | None,
    min_lifetime_rides_to_run: int,
) -> CooperativeBoardSeat:
    seat = CooperativeBoardSeat(
        name=name,
        description=description,
        term_months=term_months,
        max_consecutive_terms=max_consecutive_terms,
        min_lifetime_rides_to_run=min_lifetime_rides_to_run,
    )
    db.add(seat)
    await db.flush()
    await db.refresh(seat)
    return seat


async def get_seat(db: AsyncSession, seat_id: int) -> CooperativeBoardSeat | None:
    result = await db.execute(
        select(CooperativeBoardSeat).where(CooperativeBoardSeat.id == seat_id)
    )
    return result.scalar_one_or_none()


async def get_all_seats(
    db: AsyncSession, active_only: bool = False
) -> Sequence[CooperativeBoardSeat]:
    q = select(CooperativeBoardSeat)
    if active_only:
        q = q.where(CooperativeBoardSeat.is_active == True)  # noqa: E712
    result = await db.execute(q.order_by(CooperativeBoardSeat.name))
    return result.scalars().all()


async def update_seat(
    db: AsyncSession,
    seat_id: int,
    **fields,
) -> CooperativeBoardSeat:
    seat = await get_seat(db, seat_id)
    if seat is None:
        raise BoardElectionError(status_code=404, detail="Board seat not found.")
    for key, val in fields.items():
        if val is not None:
            setattr(seat, key, val)
    await db.flush()
    await db.refresh(seat)
    return seat


# ---------------------------------------------------------------------------
# Election lifecycle
# ---------------------------------------------------------------------------


async def create_election(
    db: AsyncSession,
    seat_id: int,
    title: str,
    description: str | None,
    min_lifetime_rides_to_vote: int,
) -> BoardElection:
    # Verify seat exists
    seat = await get_seat(db, seat_id)
    if seat is None:
        raise BoardElectionError(status_code=404, detail="Board seat not found.")

    # Block duplicate active elections for the same seat
    result = await db.execute(
        select(BoardElection).where(
            BoardElection.seat_id == seat_id,
            BoardElection.status.in_(
                [
                    ElectionStatus.nominations_open,
                    ElectionStatus.nominations_closed,
                    ElectionStatus.voting_open,
                    ElectionStatus.tallied,
                ]
            ),
        )
    )
    if result.scalar_one_or_none():
        raise BoardElectionError(
            status_code=409,
            detail="An active election already exists for this seat.",
        )

    election = BoardElection(
        seat_id=seat_id,
        title=title,
        description=description,
        min_lifetime_rides_to_vote=min_lifetime_rides_to_vote,
        status=ElectionStatus.draft,
    )
    db.add(election)
    await db.flush()
    await db.refresh(election)
    return election


async def get_election(db: AsyncSession, election_id: int) -> BoardElection | None:
    result = await db.execute(
        select(BoardElection).where(BoardElection.id == election_id)
    )
    return result.scalar_one_or_none()


async def get_elections(
    db: AsyncSession,
    seat_id: int | None = None,
    status: ElectionStatus | None = None,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[BoardElection]:
    q = select(BoardElection)
    if seat_id is not None:
        q = q.where(BoardElection.seat_id == seat_id)
    if status is not None:
        q = q.where(BoardElection.status == status)
    result = await db.execute(
        q.order_by(BoardElection.created_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()


async def open_nominations(
    db: AsyncSession,
    election_id: int,
    nominations_open_at: datetime,
    nominations_close_at: datetime,
) -> BoardElection:
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.draft:
        raise BoardElectionError(
            status_code=409,
            detail=f"Cannot open nominations from status '{election.status}'.",
        )
    if nominations_close_at <= nominations_open_at:
        raise BoardElectionError(
            status_code=422,
            detail="nominations_close_at must be after nominations_open_at.",
        )
    election.nominations_open_at = nominations_open_at
    election.nominations_close_at = nominations_close_at
    election.status = ElectionStatus.nominations_open
    await db.flush()
    await db.refresh(election)
    return election


async def close_nominations(
    db: AsyncSession, election_id: int
) -> BoardElection:
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.nominations_open:
        raise BoardElectionError(
            status_code=409,
            detail=f"Cannot close nominations from status '{election.status}'.",
        )
    election.status = ElectionStatus.nominations_closed
    await db.flush()
    await db.refresh(election)
    return election


async def open_voting(
    db: AsyncSession,
    election_id: int,
    voting_opens_at: datetime,
    voting_closes_at: datetime,
) -> BoardElection:
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.nominations_closed:
        raise BoardElectionError(
            status_code=409,
            detail=f"Cannot open voting from status '{election.status}'.",
        )
    if voting_closes_at <= voting_opens_at:
        raise BoardElectionError(
            status_code=422, detail="voting_closes_at must be after voting_opens_at."
        )

    # Must have at least one approved candidacy to open voting
    result = await db.execute(
        select(BoardCandidacy).where(
            BoardCandidacy.election_id == election_id,
            BoardCandidacy.status == CandidacyStatus.approved,
        )
    )
    if result.first() is None:
        raise BoardElectionError(
            status_code=409,
            detail="Cannot open voting: no approved candidacies.",
        )

    election.voting_opens_at = voting_opens_at
    election.voting_closes_at = voting_closes_at
    election.status = ElectionStatus.voting_open
    await db.flush()
    await db.refresh(election)
    return election


async def tally_votes(db: AsyncSession, election_id: int) -> BoardElection:
    """Close voting and compute results.  Ties broken by earliest applied_at."""
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.voting_open:
        raise BoardElectionError(
            status_code=409,
            detail=f"Cannot tally from status '{election.status}'.",
        )

    # Count votes per approved candidacy
    result = await db.execute(
        select(BoardCandidacy).where(
            BoardCandidacy.election_id == election_id,
            BoardCandidacy.status == CandidacyStatus.approved,
        )
    )
    candidacies = list(result.scalars().all())

    for candidacy in candidacies:
        vote_result = await db.execute(
            select(BoardElectionVote).where(
                BoardElectionVote.candidacy_id == candidacy.id
            )
        )
        candidacy.vote_count = len(vote_result.scalars().all())

    # Determine winner: most votes; tie → earliest applied_at
    if candidacies:
        winner = max(
            candidacies,
            key=lambda c: (c.vote_count, -c.applied_at.timestamp()),
        )
        election.winner_id = winner.driver_profile_id

    election.status = ElectionStatus.tallied
    await db.flush()
    await db.refresh(election)
    return election


async def certify_election(
    db: AsyncSession, election_id: int, certification_notes: str | None
) -> BoardElection:
    """Certify results and update the board seat's current holder."""
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.tallied:
        raise BoardElectionError(
            status_code=409,
            detail=f"Cannot certify from status '{election.status}'.",
        )

    now = datetime.now(tz=timezone.utc)
    election.status = ElectionStatus.certified
    election.certified_at = now
    election.certification_notes = certification_notes

    # Update the seat
    seat = await get_seat(db, election.seat_id)
    if seat and election.winner_id:
        seat.current_holder_id = election.winner_id
        seat.holder_term_ends_at = now + timedelta(days=seat.term_months * 30)

    await db.flush()
    await db.refresh(election)
    return election


async def cancel_election(
    db: AsyncSession, election_id: int
) -> BoardElection:
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status == ElectionStatus.certified:
        raise BoardElectionError(
            status_code=409,
            detail="Cannot cancel a certified election.",
        )
    if election.status == ElectionStatus.cancelled:
        raise BoardElectionError(
            status_code=409, detail="Election is already cancelled."
        )
    election.status = ElectionStatus.cancelled
    await db.flush()
    await db.refresh(election)
    return election


# ---------------------------------------------------------------------------
# Candidacy operations
# ---------------------------------------------------------------------------


async def apply_for_candidacy(
    db: AsyncSession,
    election_id: int,
    driver_profile_id: int,
    statement: str,
) -> BoardCandidacy:
    """Driver self-nominates.  Checks election status and ride eligibility."""
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.nominations_open:
        raise BoardElectionError(
            status_code=409,
            detail="Nominations are not currently open for this election.",
        )

    # Check for existing candidacy
    existing = await db.execute(
        select(BoardCandidacy).where(
            BoardCandidacy.election_id == election_id,
            BoardCandidacy.driver_profile_id == driver_profile_id,
        )
    )
    if existing.scalar_one_or_none():
        raise BoardElectionError(
            status_code=409,
            detail="You have already applied for this election.",
        )

    # Check ride eligibility against the seat requirement
    seat = await get_seat(db, election.seat_id)
    if seat:
        driver_result = await db.execute(
            select(DriverProfile).where(DriverProfile.id == driver_profile_id)
        )
        driver = driver_result.scalar_one_or_none()
        if driver and driver.lifetime_rides < seat.min_lifetime_rides_to_run:
            raise BoardElectionError(
                status_code=403,
                detail=(
                    f"You need at least {seat.min_lifetime_rides_to_run} completed rides "
                    "to run for this seat."
                ),
            )

    candidacy = BoardCandidacy(
        election_id=election_id,
        driver_profile_id=driver_profile_id,
        statement=statement,
        status=CandidacyStatus.pending,
    )
    db.add(candidacy)
    await db.flush()
    await db.refresh(candidacy)
    return candidacy


async def get_candidacy(
    db: AsyncSession, candidacy_id: int
) -> BoardCandidacy | None:
    result = await db.execute(
        select(BoardCandidacy).where(BoardCandidacy.id == candidacy_id)
    )
    return result.scalar_one_or_none()


async def get_election_candidacies(
    db: AsyncSession,
    election_id: int,
    approved_only: bool = False,
) -> Sequence[BoardCandidacy]:
    q = select(BoardCandidacy).where(BoardCandidacy.election_id == election_id)
    if approved_only:
        q = q.where(BoardCandidacy.status == CandidacyStatus.approved)
    result = await db.execute(q.order_by(BoardCandidacy.applied_at))
    return result.scalars().all()


async def review_candidacy(
    db: AsyncSession,
    candidacy_id: int,
    approve: bool,
    admin_notes: str | None,
) -> BoardCandidacy:
    candidacy = await get_candidacy(db, candidacy_id)
    if candidacy is None:
        raise BoardElectionError(status_code=404, detail="Candidacy not found.")
    if candidacy.status != CandidacyStatus.pending:
        raise BoardElectionError(
            status_code=409,
            detail=f"Candidacy is already in status '{candidacy.status}'.",
        )
    now = datetime.now(tz=timezone.utc)
    candidacy.status = CandidacyStatus.approved if approve else CandidacyStatus.rejected
    candidacy.admin_notes = admin_notes
    candidacy.reviewed_at = now
    await db.flush()
    await db.refresh(candidacy)
    return candidacy


async def withdraw_candidacy(
    db: AsyncSession,
    candidacy_id: int,
    driver_profile_id: int,
) -> BoardCandidacy:
    candidacy = await get_candidacy(db, candidacy_id)
    if candidacy is None:
        raise BoardElectionError(status_code=404, detail="Candidacy not found.")
    if candidacy.driver_profile_id != driver_profile_id:
        raise BoardElectionError(status_code=403, detail="Not your candidacy.")
    if candidacy.status not in (CandidacyStatus.pending, CandidacyStatus.approved):
        raise BoardElectionError(
            status_code=409,
            detail=f"Cannot withdraw candidacy in status '{candidacy.status}'.",
        )
    candidacy.status = CandidacyStatus.withdrawn
    await db.flush()
    await db.refresh(candidacy)
    return candidacy


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------


async def cast_vote(
    db: AsyncSession,
    election_id: int,
    candidacy_id: int,
    voter_driver_profile_id: int,
) -> BoardElectionVote:
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status != ElectionStatus.voting_open:
        raise BoardElectionError(
            status_code=409, detail="Voting is not currently open."
        )

    # Verify the candidacy belongs to this election and is approved
    candidacy = await get_candidacy(db, candidacy_id)
    if candidacy is None or candidacy.election_id != election_id:
        raise BoardElectionError(
            status_code=404, detail="Candidacy not found in this election."
        )
    if candidacy.status != CandidacyStatus.approved:
        raise BoardElectionError(
            status_code=409, detail="You can only vote for approved candidates."
        )

    # Check eligibility
    driver_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == voter_driver_profile_id)
    )
    driver = driver_result.scalar_one_or_none()
    if driver and driver.lifetime_rides < election.min_lifetime_rides_to_vote:
        raise BoardElectionError(
            status_code=403,
            detail=(
                f"You need at least {election.min_lifetime_rides_to_vote} completed "
                "rides to vote in this election."
            ),
        )

    # Idempotency guard — one vote per driver per election
    existing = await db.execute(
        select(BoardElectionVote).where(
            BoardElectionVote.election_id == election_id,
            BoardElectionVote.voter_driver_profile_id == voter_driver_profile_id,
        )
    )
    if existing.scalar_one_or_none():
        raise BoardElectionError(
            status_code=409, detail="You have already voted in this election."
        )

    vote = BoardElectionVote(
        election_id=election_id,
        candidacy_id=candidacy_id,
        voter_driver_profile_id=voter_driver_profile_id,
    )
    db.add(vote)
    await db.flush()
    await db.refresh(vote)
    return vote


async def get_election_results(
    db: AsyncSession, election_id: int
) -> dict:
    """Return tally results.  Only meaningful after status = tallied."""
    election = await get_election(db, election_id)
    if election is None:
        raise BoardElectionError(status_code=404, detail="Election not found.")
    if election.status not in (ElectionStatus.tallied, ElectionStatus.certified):
        raise BoardElectionError(
            status_code=409,
            detail="Results are not yet available — election has not been tallied.",
        )

    result = await db.execute(
        select(BoardCandidacy).where(
            BoardCandidacy.election_id == election_id,
            BoardCandidacy.status == CandidacyStatus.approved,
        )
    )
    candidacies = list(result.scalars().all())

    total_votes = sum(c.vote_count for c in candidacies)

    return {
        "election_id": election_id,
        "status": election.status,
        "total_votes": total_votes,
        "candidacies": candidacies,
        "winner_id": election.winner_id,
        "certified_at": election.certified_at,
    }


async def get_board_roster(db: AsyncSession) -> Sequence[CooperativeBoardSeat]:
    result = await db.execute(
        select(CooperativeBoardSeat)
        .where(CooperativeBoardSeat.is_active == True)  # noqa: E712
        .order_by(CooperativeBoardSeat.name)
    )
    return result.scalars().all()
