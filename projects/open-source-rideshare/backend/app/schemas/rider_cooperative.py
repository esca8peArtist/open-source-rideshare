"""Schemas for rider cooperative membership, voting, and dividend endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Membership requests
# ---------------------------------------------------------------------------

class MembershipApplicationRequest(BaseModel):
    """Rider applies to join the cooperative as a member-owner."""
    # No fields required — application is tied to the authenticated rider.
    # Future: could add a statement of interest.


class SuspendMemberRequest(BaseModel):
    reason: str | None = None


class ReinstateMemberRequest(BaseModel):
    note: str | None = None


# ---------------------------------------------------------------------------
# Membership responses
# ---------------------------------------------------------------------------

class RiderCoopMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rider_id: int
    status: str
    lifetime_rides: int
    voting_weight: int
    applied_at: datetime
    approved_at: datetime | None
    suspended_at: datetime | None
    resigned_at: datetime | None
    suspension_reason: str | None


class RiderCoopMembershipListResponse(BaseModel):
    total: int
    items: list[RiderCoopMembershipResponse]


# ---------------------------------------------------------------------------
# Voting requests / responses
# ---------------------------------------------------------------------------

class RiderVoteRequest(BaseModel):
    choice: str = Field(pattern="^(yes|no|abstain)$")


class RiderVoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proposal_id: int
    rider_id: int
    choice: str
    voting_weight: int
    voted_at: datetime


class ProposalSummary(BaseModel):
    """Lightweight view of an open proposal shown to rider-members."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    proposal_type: str
    status: str
    voting_ends_at: datetime | None
    rider_votes_open: bool  # True when status == open


class ProposalRiderTallyResponse(BaseModel):
    """Rider-side vote tally for a proposal."""
    proposal_id: int
    yes_votes: int
    no_votes: int
    abstain_votes: int
    yes_weight: int
    no_weight: int
    abstain_weight: int
    total_voters: int
    my_vote: str | None  # null if caller hasn't voted


# ---------------------------------------------------------------------------
# Dividend share responses
# ---------------------------------------------------------------------------

class RiderDividendShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dividend_id: int
    rider_id: int
    qualifying_rides: int
    share_pct: float
    amount_usd: float
    status: str
    paid_at: datetime | None


class RiderDividendShareListResponse(BaseModel):
    total: int
    items: list[RiderDividendShareResponse]


# ---------------------------------------------------------------------------
# Admin: generate rider shares for a dividend period
# ---------------------------------------------------------------------------

class GenerateRiderSharesRequest(BaseModel):
    dividend_id: int = Field(ge=1, description="ID of an approved CooperativeDividend")
    rider_surplus_usd: float = Field(
        gt=0,
        description="Portion of platform surplus earmarked for rider-members (USD)",
    )


# ---------------------------------------------------------------------------
# Admin summary
# ---------------------------------------------------------------------------

class RiderCoopSummaryResponse(BaseModel):
    total_members: int
    active_members: int
    applicants_pending: int
    suspended_members: int
    resigned_members: int
    total_dividends_paid_usd: float
    total_dividends_pending_usd: float
