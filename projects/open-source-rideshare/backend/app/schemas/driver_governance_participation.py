"""Pydantic schemas for the driver governance participation report endpoint.

GET /drivers/me/governance-participation

A cooperative platform is owned and governed by its driver-members.  Drivers
vote on proposals (fee rates, bonus structures, policy changes) and elect board
representatives.  This endpoint surfaces a driver's full governance
participation history — how many proposals they've voted on, their vote
breakdown, board elections they've participated in, and what's currently open
for their input.

No Uber or Lyft equivalent exists.  This is a uniquely cooperative feature:
member-owners have a right to know their own civic engagement record.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OpenProposalSummary(BaseModel):
    """Brief summary of an open proposal the driver has not yet voted on."""

    proposal_id: int = Field(..., description="Unique proposal identifier.")
    title: str = Field(..., description="Short title of the proposal.")
    proposal_type: str = Field(
        ...,
        description=(
            "Category: 'fee_rate_change', 'bonus_structure', 'policy_change', "
            "'platform_feature', or 'general'."
        ),
    )
    voting_closes_at: Optional[datetime] = Field(
        None,
        description="UTC datetime when the voting window closes.  None if not yet set.",
    )
    votes_for: int = Field(..., description="Running yes-vote tally.")
    votes_against: int = Field(..., description="Running no-vote tally.")
    votes_abstain: int = Field(..., description="Running abstain tally.")


class OpenElectionSummary(BaseModel):
    """Brief summary of a board election currently accepting nominations."""

    election_id: int = Field(..., description="Unique election identifier.")
    title: str = Field(..., description="Election title (e.g. 'Board Seat — Driver Safety').")
    seat_name: str = Field(..., description="Name of the board seat being contested.")
    status: str = Field(
        ...,
        description=(
            "Current election phase: 'nominations_open' or 'voting_open'."
        ),
    )
    nominations_close_at: Optional[datetime] = Field(
        None,
        description="UTC datetime when nominations close.  None if not applicable.",
    )
    voting_closes_at: Optional[datetime] = Field(
        None,
        description="UTC datetime when voting closes.  None if voting not yet open.",
    )
    driver_is_candidate: bool = Field(
        ...,
        description="True if the authenticated driver has an approved candidacy in this election.",
    )
    driver_has_voted: bool = Field(
        ...,
        description="True if the authenticated driver has already cast a ballot.",
    )


class VoteBreakdown(BaseModel):
    """Count of yes/no/abstain votes cast across all proposals."""

    yes: int = Field(0, description="Number of 'yes' votes cast.")
    no: int = Field(0, description="Number of 'no' votes cast.")
    abstain: int = Field(0, description="Number of 'abstain' votes cast.")


class DriverGovernanceParticipation(BaseModel):
    """Comprehensive governance participation report for the authenticated driver.

    Surfaces the driver's full history of cooperative civic engagement:
    proposals submitted, votes cast, board elections participated in, and
    what is currently open.  A cooperative platform owes its member-owners
    this visibility.
    """

    # Proposals submitted by the driver
    proposals_submitted: int = Field(
        ...,
        description="Total proposals the driver has submitted (any status).",
    )
    proposals_submitted_passed: int = Field(
        ...,
        description=(
            "Driver-submitted proposals that reached 'passed' or 'implemented' status.  "
            "A measure of the driver's legislative effectiveness as a member-owner."
        ),
    )

    # Voting on proposals
    total_votes_cast: int = Field(
        ...,
        description="Total proposal votes the driver has cast (all time).",
    )
    vote_breakdown: VoteBreakdown = Field(
        ...,
        description="Breakdown of yes/no/abstain across all proposal votes cast.",
    )
    proposals_eligible: int = Field(
        ...,
        description=(
            "Total non-draft, non-withdrawn proposals the driver was eligible to vote on "
            "based on their current lifetime ride count.  Used as the participation rate "
            "denominator.  This is an approximation — it uses current ride count, not "
            "historical ride count at the time each proposal was open."
        ),
    )
    participation_rate_pct: Optional[float] = Field(
        None,
        description=(
            "Percentage of eligible proposals on which the driver cast a vote: "
            "(total_votes_cast / proposals_eligible) × 100.  "
            "None when proposals_eligible is 0."
        ),
    )

    # Board elections
    board_elections_participated: int = Field(
        ...,
        description="Number of board elections in which the driver cast a secret ballot.",
    )
    board_elections_ran: int = Field(
        ...,
        description=(
            "Number of board elections in which the driver submitted a candidacy "
            "(any candidacy status: pending, approved, rejected, withdrawn)."
        ),
    )
    board_elections_won: int = Field(
        ...,
        description="Number of board elections the driver won (certified as winner).",
    )

    # Engagement tier
    engagement_tier: str = Field(
        ...,
        description=(
            "Categorical governance engagement level: "
            "'active' (participation ≥ 75%), "
            "'engaged' (50–74%), "
            "'occasional' (1–49%, or any vote cast with low eligibility count), "
            "'new' (0 votes and < 50 lifetime rides), "
            "'eligible_not_participating' (eligible for votes but cast none)."
        ),
    )

    # Open items needing the driver's attention
    open_proposals_awaiting_vote: list[OpenProposalSummary] = Field(
        default_factory=list,
        description=(
            "Proposals currently open for voting that the driver has not yet voted on "
            "and is eligible to vote on.  Sorted by voting_closes_at ascending (soonest first)."
        ),
    )
    active_elections: list[OpenElectionSummary] = Field(
        default_factory=list,
        description=(
            "Board elections currently accepting nominations or votes.  "
            "Includes driver's candidacy and vote status for each."
        ),
    )

    # Plain-language summary
    participation_note: str = Field(
        ...,
        description=(
            "Human-readable sentence summarising the driver's governance engagement.  "
            "Suitable for display as a dashboard card."
        ),
    )

    report_generated_at: datetime = Field(
        ...,
        description="UTC timestamp when this report was generated.",
    )
