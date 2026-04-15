"""Pydantic schemas for cooperative governance — driver proposals and voting."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_proposal import ProposalStatus, ProposalType, VoteChoice


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateProposalRequest(BaseModel):
    """Shared request body for admin and driver proposal creation."""

    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=10)
    proposal_type: ProposalType
    min_lifetime_rides_to_vote: int = Field(50, ge=0, le=5000)
    result_threshold_pct: float = Field(0.5001, ge=0.5, le=1.0)


class AdminCreateProposalRequest(CreateProposalRequest):
    """Admin creation also allows setting the initial open window."""

    voting_opens_at: datetime | None = None
    voting_closes_at: datetime | None = None
    open_immediately: bool = False  # if True, status becomes open right away


class UpdateProposalRequest(BaseModel):
    """Admin updates after creation."""

    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = None
    implementation_notes: str | None = None
    voting_opens_at: datetime | None = None
    voting_closes_at: datetime | None = None


class CastVoteRequest(BaseModel):
    vote: VoteChoice


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ProposalSummary(BaseModel):
    """Lightweight listing view — no vote breakdown."""

    id: int
    title: str
    proposal_type: ProposalType
    status: ProposalStatus
    created_by_admin: bool
    voting_opens_at: datetime | None
    voting_closes_at: datetime | None
    votes_for: int
    votes_against: int
    votes_abstain: int
    total_votes: int
    result_threshold_pct: float
    min_lifetime_rides_to_vote: int
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_extended(cls, obj: object) -> "ProposalSummary":
        return cls(
            id=obj.id,  # type: ignore[attr-defined]
            title=obj.title,  # type: ignore[attr-defined]
            proposal_type=obj.proposal_type,  # type: ignore[attr-defined]
            status=obj.status,  # type: ignore[attr-defined]
            created_by_admin=obj.created_by_admin,  # type: ignore[attr-defined]
            voting_opens_at=obj.voting_opens_at,  # type: ignore[attr-defined]
            voting_closes_at=obj.voting_closes_at,  # type: ignore[attr-defined]
            votes_for=obj.votes_for,  # type: ignore[attr-defined]
            votes_against=obj.votes_against,  # type: ignore[attr-defined]
            votes_abstain=obj.votes_abstain,  # type: ignore[attr-defined]
            total_votes=obj.votes_for + obj.votes_against + obj.votes_abstain,  # type: ignore[attr-defined]
            result_threshold_pct=float(obj.result_threshold_pct),  # type: ignore[attr-defined]
            min_lifetime_rides_to_vote=obj.min_lifetime_rides_to_vote,  # type: ignore[attr-defined]
            created_at=obj.created_at,  # type: ignore[attr-defined]
        )


class ProposalDetail(ProposalSummary):
    """Full detail view including description and outcome data."""

    description: str
    implementation_notes: str | None
    implemented_at: datetime | None
    updated_at: datetime
    # Derived pass/fail percentage (None while still open)
    yes_pct: float | None

    @classmethod
    def from_orm_extended(cls, obj: object) -> "ProposalDetail":  # type: ignore[override]
        votes_for = obj.votes_for  # type: ignore[attr-defined]
        votes_against = obj.votes_against  # type: ignore[attr-defined]
        votes_abstain = obj.votes_abstain  # type: ignore[attr-defined]
        decisive = votes_for + votes_against
        yes_pct = round(votes_for / decisive * 100, 1) if decisive > 0 else None
        return cls(
            id=obj.id,  # type: ignore[attr-defined]
            title=obj.title,  # type: ignore[attr-defined]
            description=obj.description,  # type: ignore[attr-defined]
            proposal_type=obj.proposal_type,  # type: ignore[attr-defined]
            status=obj.status,  # type: ignore[attr-defined]
            created_by_admin=obj.created_by_admin,  # type: ignore[attr-defined]
            voting_opens_at=obj.voting_opens_at,  # type: ignore[attr-defined]
            voting_closes_at=obj.voting_closes_at,  # type: ignore[attr-defined]
            votes_for=votes_for,
            votes_against=votes_against,
            votes_abstain=votes_abstain,
            total_votes=votes_for + votes_against + votes_abstain,
            result_threshold_pct=float(obj.result_threshold_pct),  # type: ignore[attr-defined]
            min_lifetime_rides_to_vote=obj.min_lifetime_rides_to_vote,  # type: ignore[attr-defined]
            created_at=obj.created_at,  # type: ignore[attr-defined]
            implementation_notes=obj.implementation_notes,  # type: ignore[attr-defined]
            implemented_at=obj.implemented_at,  # type: ignore[attr-defined]
            updated_at=obj.updated_at,  # type: ignore[attr-defined]
            yes_pct=yes_pct,
        )


class VoteResponse(BaseModel):
    proposal_id: int
    vote: VoteChoice
    voted_at: datetime

    model_config = {"from_attributes": True}


class MyVoteResponse(BaseModel):
    """Null when the driver hasn't voted yet."""

    proposal_id: int
    voted: bool
    vote: VoteChoice | None
    voted_at: datetime | None

    model_config = {"from_attributes": True}


class ProposalListResponse(BaseModel):
    proposals: list[ProposalSummary]
    total: int
    offset: int
    limit: int


class AdminCloseResultResponse(BaseModel):
    proposal_id: int
    status: ProposalStatus
    votes_for: int
    votes_against: int
    votes_abstain: int
    yes_pct: float | None
    passed: bool
    threshold_required_pct: float
