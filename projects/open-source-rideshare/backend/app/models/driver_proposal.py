"""Cooperative governance: driver proposals and voting.

Driver-owners of the cooperative can submit and vote on platform proposals —
fee rate changes, bonus structures, policy changes, and general platform
decisions. This is the democratic backbone that distinguishes a cooperative
from a traditional rideshare company.

Lifecycle:
  draft  → open (voting begins) → closed → passed | failed
  draft  → withdrawn            (before voting opens)
  passed → implemented          (admin marks as enacted)

Eligibility to vote: driver must have >= min_lifetime_rides_to_vote
completed rides. This threshold is set per proposal (default 50) so high-
stakes proposals (fee changes) can require more established members.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ProposalType(str, enum.Enum):
    fee_rate_change = "fee_rate_change"
    bonus_structure = "bonus_structure"
    policy_change = "policy_change"
    platform_feature = "platform_feature"
    general = "general"


class ProposalStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    closed = "closed"
    passed = "passed"
    failed = "failed"
    withdrawn = "withdrawn"
    implemented = "implemented"


class VoteChoice(str, enum.Enum):
    yes = "yes"
    no = "no"
    abstain = "abstain"


class DriverProposal(Base):
    """A platform proposal that eligible driver-owners can vote on."""

    __tablename__ = "driver_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)

    proposal_type: Mapped[ProposalType] = mapped_column(Enum(ProposalType))

    # Who created this? null = system / admin. Non-null = a specific user.
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    # Distinguishes admin-initiated from driver-initiated proposals.
    created_by_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.draft, index=True
    )

    # Voting window — null until proposal is formally opened.
    voting_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # How many completed lifetime rides a driver needs to cast a vote.
    # Higher value = more established members only. Default 50.
    min_lifetime_rides_to_vote: Mapped[int] = mapped_column(Integer, default=50)

    # Cached vote tallies — updated on every cast vote.
    votes_for: Mapped[int] = mapped_column(Integer, default=0)
    votes_against: Mapped[int] = mapped_column(Integer, default=0)
    votes_abstain: Mapped[int] = mapped_column(Integer, default=0)

    # Fraction of yes/(yes+no) required to pass (abstentions excluded).
    # 0.5001 = simple majority; 0.6667 = two-thirds supermajority.
    result_threshold_pct: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0.5001
    )

    # Post-result fields
    implementation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    implemented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    created_by = relationship("User", foreign_keys=[created_by_user_id], backref="proposals")
    votes = relationship("DriverVote", back_populates="proposal", cascade="all, delete-orphan")


class DriverVote(Base):
    """A single driver's vote on a proposal."""

    __tablename__ = "driver_votes"

    id: Mapped[int] = mapped_column(primary_key=True)

    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("driver_proposals.id"), index=True
    )
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )

    vote: Mapped[VoteChoice] = mapped_column(Enum(VoteChoice))

    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "proposal_id",
            "driver_profile_id",
            name="uq_driver_vote_proposal_driver",
        ),
    )

    proposal = relationship("DriverProposal", back_populates="votes")
    driver_profile = relationship("DriverProfile", backref="votes_cast")
