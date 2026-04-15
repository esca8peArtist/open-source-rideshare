"""Cooperative Board Election endpoints.

Public:
  GET  /cooperative/board/roster          — current board roster (all users)
  GET  /cooperative/board/seats           — list active seats (all users)

Driver-facing (authenticated driver):
  GET  /cooperative/elections             — list elections (filter by status/seat)
  GET  /cooperative/elections/{id}        — election detail
  GET  /cooperative/elections/{id}/candidacies  — approved candidacies + statements
  POST /cooperative/elections/{id}/candidacy    — self-nominate
  DELETE /cooperative/elections/{id}/candidacy  — withdraw candidacy
  POST /cooperative/elections/{id}/vote         — cast a secret ballot

Admin-facing:
  POST /cooperative/board/seats               — create seat
  PUT  /cooperative/board/seats/{seat_id}     — update seat
  POST /cooperative/elections                 — create election (draft)
  POST /cooperative/elections/{id}/open-nominations  — open nomination window
  POST /cooperative/elections/{id}/close-nominations — close nomination window
  POST /cooperative/elections/{id}/open-voting       — open voting window
  POST /cooperative/elections/{id}/tally             — tally votes
  POST /cooperative/elections/{id}/certify           — certify and update roster
  POST /cooperative/elections/{id}/cancel            — cancel election
  GET  /cooperative/elections/{id}/results           — full tally results (admin)
  POST /cooperative/elections/{id}/candidacies/{cid}/review — approve/reject candidacy
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_driver
from app.models.board_election import ElectionStatus
from app.schemas.board_election import (
    ApplyForCandidacyRequest,
    BoardRosterEntry,
    BoardSeatResponse,
    CandidacyResponse,
    CandidacyResultResponse,
    CertifyElectionRequest,
    CreateBoardSeatRequest,
    CreateElectionRequest,
    ElectionResponse,
    ElectionResultsResponse,
    OpenNominationsRequest,
    OpenVotingRequest,
    ReviewCandidacyRequest,
    UpdateBoardSeatRequest,
)
from app.services import board_election as svc

router = APIRouter(tags=["board-elections"])


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/cooperative/board/roster",
    response_model=list[BoardRosterEntry],
    summary="Current cooperative board roster",
)
async def get_board_roster(db: AsyncSession = Depends(get_db)):
    seats = await svc.get_board_roster(db)
    return [
        BoardRosterEntry(
            seat_id=s.id,
            seat_name=s.name,
            description=s.description,
            current_holder_id=s.current_holder_id,
            holder_term_ends_at=s.holder_term_ends_at,
        )
        for s in seats
    ]


@router.get(
    "/cooperative/board/seats",
    response_model=list[BoardSeatResponse],
    summary="List board seats",
)
async def list_seats(db: AsyncSession = Depends(get_db)):
    seats = await svc.get_all_seats(db, active_only=True)
    return seats


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/cooperative/elections",
    response_model=list[ElectionResponse],
    summary="List board elections",
)
async def list_elections(
    seat_id: Annotated[int | None, Query()] = None,
    status: Annotated[ElectionStatus | None, Query()] = None,
    skip: int = 0,
    limit: int = 50,
    _driver=Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_elections(db, seat_id=seat_id, status=status, skip=skip, limit=limit)


@router.get(
    "/cooperative/elections/{election_id}",
    response_model=ElectionResponse,
    summary="Get election detail",
)
async def get_election(
    election_id: int,
    _driver=Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.get_election(db, election_id)
    if election is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Election not found.")
    return election


@router.get(
    "/cooperative/elections/{election_id}/candidacies",
    response_model=list[CandidacyResponse],
    summary="List approved candidacies (the ballot)",
)
async def list_candidacies(
    election_id: int,
    _driver=Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    # Drivers see only approved candidacies
    return await svc.get_election_candidacies(db, election_id, approved_only=True)


@router.post(
    "/cooperative/elections/{election_id}/candidacy",
    response_model=CandidacyResponse,
    status_code=201,
    summary="Self-nominate as a candidate",
)
async def apply_for_candidacy(
    election_id: int,
    body: ApplyForCandidacyRequest,
    driver=Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    candidacy = await svc.apply_for_candidacy(
        db,
        election_id=election_id,
        driver_profile_id=driver.id,
        statement=body.statement,
    )
    await db.commit()
    await db.refresh(candidacy)
    return candidacy


@router.delete(
    "/cooperative/elections/{election_id}/candidacy",
    response_model=CandidacyResponse,
    summary="Withdraw your candidacy",
)
async def withdraw_candidacy(
    election_id: int,
    driver=Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    # Find the driver's own candidacy in this election
    candidacies = await svc.get_election_candidacies(db, election_id)
    mine = next(
        (c for c in candidacies if c.driver_profile_id == driver.id), None
    )
    if mine is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No candidacy found for this election.")
    result = await svc.withdraw_candidacy(db, candidacy_id=mine.id, driver_profile_id=driver.id)
    await db.commit()
    await db.refresh(result)
    return result


@router.post(
    "/cooperative/elections/{election_id}/vote",
    response_model=dict,
    status_code=201,
    summary="Cast a secret ballot",
)
async def cast_vote(
    election_id: int,
    candidacy_id: Annotated[int, Query(description="ID of the candidacy to vote for")],
    driver=Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    vote = await svc.cast_vote(
        db,
        election_id=election_id,
        candidacy_id=candidacy_id,
        voter_driver_profile_id=driver.id,
    )
    await db.commit()
    return {"message": "Vote recorded.", "voted_at": vote.voted_at.isoformat()}


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/cooperative/board/seats",
    response_model=BoardSeatResponse,
    status_code=201,
    summary="Create a board seat (admin)",
)
async def create_seat(
    body: CreateBoardSeatRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    seat = await svc.create_seat(
        db,
        name=body.name,
        description=body.description,
        term_months=body.term_months,
        max_consecutive_terms=body.max_consecutive_terms,
        min_lifetime_rides_to_run=body.min_lifetime_rides_to_run,
    )
    await db.commit()
    await db.refresh(seat)
    return seat


@router.put(
    "/cooperative/board/seats/{seat_id}",
    response_model=BoardSeatResponse,
    summary="Update a board seat (admin)",
)
async def update_seat(
    seat_id: int,
    body: UpdateBoardSeatRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    seat = await svc.update_seat(
        db,
        seat_id=seat_id,
        **body.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(seat)
    return seat


@router.post(
    "/cooperative/elections",
    response_model=ElectionResponse,
    status_code=201,
    summary="Create a board election (admin, draft)",
)
async def create_election(
    body: CreateElectionRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.create_election(
        db,
        seat_id=body.seat_id,
        title=body.title,
        description=body.description,
        min_lifetime_rides_to_vote=body.min_lifetime_rides_to_vote,
    )
    await db.commit()
    await db.refresh(election)
    return election


@router.post(
    "/cooperative/elections/{election_id}/open-nominations",
    response_model=ElectionResponse,
    summary="Open the nomination window (admin)",
)
async def open_nominations(
    election_id: int,
    body: OpenNominationsRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.open_nominations(
        db,
        election_id=election_id,
        nominations_open_at=body.nominations_open_at,
        nominations_close_at=body.nominations_close_at,
    )
    await db.commit()
    await db.refresh(election)
    return election


@router.post(
    "/cooperative/elections/{election_id}/close-nominations",
    response_model=ElectionResponse,
    summary="Close the nomination window (admin)",
)
async def close_nominations(
    election_id: int,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.close_nominations(db, election_id)
    await db.commit()
    await db.refresh(election)
    return election


@router.post(
    "/cooperative/elections/{election_id}/open-voting",
    response_model=ElectionResponse,
    summary="Open the voting window (admin)",
)
async def open_voting(
    election_id: int,
    body: OpenVotingRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.open_voting(
        db,
        election_id=election_id,
        voting_opens_at=body.voting_opens_at,
        voting_closes_at=body.voting_closes_at,
    )
    await db.commit()
    await db.refresh(election)
    return election


@router.post(
    "/cooperative/elections/{election_id}/tally",
    response_model=ElectionResponse,
    summary="Tally votes and determine winner (admin)",
)
async def tally_votes(
    election_id: int,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.tally_votes(db, election_id)
    await db.commit()
    await db.refresh(election)
    return election


@router.post(
    "/cooperative/elections/{election_id}/certify",
    response_model=ElectionResponse,
    summary="Certify election results and install winner (admin)",
)
async def certify_election(
    election_id: int,
    body: CertifyElectionRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.certify_election(db, election_id, body.certification_notes)
    await db.commit()
    await db.refresh(election)
    return election


@router.post(
    "/cooperative/elections/{election_id}/cancel",
    response_model=ElectionResponse,
    summary="Cancel an election (admin)",
)
async def cancel_election(
    election_id: int,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    election = await svc.cancel_election(db, election_id)
    await db.commit()
    await db.refresh(election)
    return election


@router.get(
    "/cooperative/elections/{election_id}/results",
    response_model=ElectionResultsResponse,
    summary="Get full tally results (admin, after tallying)",
)
async def get_election_results(
    election_id: int,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    data = await svc.get_election_results(db, election_id)
    return ElectionResultsResponse(
        election_id=data["election_id"],
        status=data["status"],
        total_votes=data["total_votes"],
        candidacies=[
            CandidacyResultResponse(
                id=c.id,
                election_id=c.election_id,
                driver_profile_id=c.driver_profile_id,
                statement=c.statement,
                status=c.status,
                vote_count=c.vote_count,
                applied_at=c.applied_at,
            )
            for c in data["candidacies"]
        ],
        winner_id=data["winner_id"],
        certified_at=data["certified_at"],
    )


@router.get(
    "/cooperative/elections/admin/all",
    response_model=list[ElectionResponse],
    summary="List all elections including drafts and cancelled (admin)",
)
async def list_all_elections(
    seat_id: Annotated[int | None, Query()] = None,
    skip: int = 0,
    limit: int = 50,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_elections(db, seat_id=seat_id, skip=skip, limit=limit)


@router.get(
    "/cooperative/elections/{election_id}/candidacies/admin",
    response_model=list[CandidacyResponse],
    summary="List all candidacies including pending and rejected (admin)",
)
async def list_all_candidacies_admin(
    election_id: int,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_election_candidacies(db, election_id, approved_only=False)


@router.post(
    "/cooperative/elections/{election_id}/candidacies/{candidacy_id}/review",
    response_model=CandidacyResponse,
    summary="Approve or reject a candidacy (admin)",
)
async def review_candidacy(
    election_id: int,
    candidacy_id: int,
    body: ReviewCandidacyRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    candidacy = await svc.review_candidacy(
        db,
        candidacy_id=candidacy_id,
        approve=body.approve,
        admin_notes=body.admin_notes,
    )
    await db.commit()
    await db.refresh(candidacy)
    return candidacy
