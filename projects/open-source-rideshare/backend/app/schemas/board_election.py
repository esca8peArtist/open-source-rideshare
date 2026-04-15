"""Pydantic schemas for Cooperative Board Election endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.board_election import CandidacyStatus, ElectionStatus


# ---------------------------------------------------------------------------
# Board Seat schemas
# ---------------------------------------------------------------------------


class CreateBoardSeatRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    term_months: int = Field(12, gt=0)
    max_consecutive_terms: int | None = Field(None, gt=0)
    min_lifetime_rides_to_run: int = Field(100, ge=0)


class UpdateBoardSeatRequest(BaseModel):
    description: str | None = None
    term_months: int | None = Field(None, gt=0)
    max_consecutive_terms: int | None = Field(None, gt=0)
    min_lifetime_rides_to_run: int | None = Field(None, ge=0)
    is_active: bool | None = None


class BoardSeatResponse(BaseModel):
    id: int
    name: str
    description: str | None
    term_months: int
    max_consecutive_terms: int | None
    min_lifetime_rides_to_run: int
    current_holder_id: int | None
    holder_term_ends_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Election schemas
# ---------------------------------------------------------------------------


class CreateElectionRequest(BaseModel):
    seat_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    min_lifetime_rides_to_vote: int = Field(50, ge=0)


class OpenNominationsRequest(BaseModel):
    nominations_open_at: datetime
    nominations_close_at: datetime


class OpenVotingRequest(BaseModel):
    voting_opens_at: datetime
    voting_closes_at: datetime


class CertifyElectionRequest(BaseModel):
    certification_notes: str | None = None


class ElectionResponse(BaseModel):
    id: int
    seat_id: int
    title: str
    description: str | None
    status: ElectionStatus
    nominations_open_at: datetime | None
    nominations_close_at: datetime | None
    voting_opens_at: datetime | None
    voting_closes_at: datetime | None
    min_lifetime_rides_to_vote: int
    winner_id: int | None
    certified_at: datetime | None
    certification_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Candidacy schemas
# ---------------------------------------------------------------------------


class ApplyForCandidacyRequest(BaseModel):
    statement: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="Candidate's platform statement visible to all voters.",
    )


class ReviewCandidacyRequest(BaseModel):
    approve: bool
    admin_notes: str | None = None


class CandidacyResponse(BaseModel):
    id: int
    election_id: int
    driver_profile_id: int
    statement: str
    status: CandidacyStatus
    admin_notes: str | None
    # vote_count hidden until election is tallied — see CandidacyResultResponse
    applied_at: datetime
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


class CandidacyResultResponse(BaseModel):
    """Candidacy with vote count — only returned after election is tallied."""

    id: int
    election_id: int
    driver_profile_id: int
    statement: str
    status: CandidacyStatus
    vote_count: int
    applied_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class ElectionResultsResponse(BaseModel):
    election_id: int
    status: ElectionStatus
    total_votes: int
    candidacies: list[CandidacyResultResponse]
    winner_id: int | None
    certified_at: datetime | None


# ---------------------------------------------------------------------------
# Board roster
# ---------------------------------------------------------------------------


class BoardRosterEntry(BaseModel):
    seat_id: int
    seat_name: str
    description: str | None
    current_holder_id: int | None
    holder_term_ends_at: datetime | None

    model_config = {"from_attributes": True}
