"""Rider cooperative membership, voting, and dividend models.

Riders who join as cooperative member-owners gain voting rights on platform
proposals and receive a share of quarterly platform surplus distributions.

This complements the driver-side cooperative system (driver_dividend.py,
driver_proposal.py) and makes the rideshare platform a true multi-stakeholder
cooperative where both drivers and riders own and govern the platform.

Lifecycle:
  RiderCoopMembership:
    applicant → member      (admin approves)
    member    → suspended   (admin action)
    suspended → member      (admin reinstates)
    member    → resigned    (rider self-serves)

  RiderDividendShare: pending → paid | cancelled

Voting weight is calculated from lifetime_rides:
  weight = min(1 + lifetime_rides // 100, MAX_VOTING_WEIGHT)
  This rewards long-term riders without letting any single rider dominate.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
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

MAX_VOTING_WEIGHT = 5


class RiderMemberStatus(str, enum.Enum):
    applicant = "applicant"   # application submitted, pending admin review
    member = "member"         # active cooperative member
    suspended = "suspended"   # suspended by admin (e.g. policy violation)
    resigned = "resigned"     # voluntarily left the cooperative


class RiderCoopMembership(Base):
    """A rider's cooperative membership record.

    One row per rider — unique. Riders apply once; if they resign they can
    re-apply (creates a new row with applicant status).
    """

    __tablename__ = "rider_coop_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)

    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    status: Mapped[RiderMemberStatus] = mapped_column(
        SAEnum(RiderMemberStatus),
        nullable=False,
        default=RiderMemberStatus.applicant,
        index=True,
    )

    # Participation metrics — updated at dividend generation time
    lifetime_rides: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Voting weight: 1 base + 1 per 100 lifetime rides, capped at MAX_VOTING_WEIGHT.
    # Stored so it can be snapshotted at vote time without recomputing.
    voting_weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Admin who approved / suspended this membership
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rider = relationship("User", foreign_keys=[rider_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    votes = relationship(
        "RiderCoopVote", back_populates="membership", cascade="all, delete-orphan"
    )
    dividend_shares = relationship(
        "RiderDividendShare", back_populates="membership", cascade="all, delete-orphan"
    )


class RiderVoteChoice(str, enum.Enum):
    yes = "yes"
    no = "no"
    abstain = "abstain"


class RiderCoopVote(Base):
    """A rider-member's vote on a cooperative proposal.

    Riders vote on the same DriverProposal records that drivers use, but
    their votes are stored separately so tallies can be reported by
    stakeholder group (driver votes vs. rider votes). Admin decides whether
    rider votes are advisory or binding per proposal.
    """

    __tablename__ = "rider_coop_votes"
    __table_args__ = (
        UniqueConstraint("proposal_id", "membership_id", name="uq_rider_vote_proposal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("driver_proposals.id"), nullable=False, index=True
    )
    membership_id: Mapped[int] = mapped_column(
        ForeignKey("rider_coop_memberships.id"), nullable=False, index=True
    )
    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    choice: Mapped[RiderVoteChoice] = mapped_column(
        SAEnum(RiderVoteChoice), nullable=False
    )

    # Voting weight snapshotted at cast time so later membership changes
    # don't retroactively alter vote tallies.
    voting_weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    membership = relationship("RiderCoopMembership", back_populates="votes")
    rider = relationship("User", foreign_keys=[rider_id])


class RiderDividendShareStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    cancelled = "cancelled"


class RiderDividendShare(Base):
    """A rider-member's allocation within a cooperative dividend distribution.

    When the platform declares a surplus via CooperativeDividend, admin can
    optionally earmark a portion for rider-members (e.g. 10% of surplus goes
    to riders, 90% to drivers). This table tracks each rider's individual share.

    Shares are proportional to qualifying_rides in the dividend period.
    """

    __tablename__ = "rider_dividend_shares"
    __table_args__ = (
        UniqueConstraint(
            "dividend_id", "membership_id", name="uq_rider_dividend_share"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    dividend_id: Mapped[int] = mapped_column(
        ForeignKey("cooperative_dividends.id"), nullable=False, index=True
    )
    membership_id: Mapped[int] = mapped_column(
        ForeignKey("rider_coop_memberships.id"), nullable=False, index=True
    )
    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Rides taken in the dividend quarter.
    qualifying_rides: Mapped[int] = mapped_column(Integer, default=0)

    # This rider's share as a percentage of total qualifying rider rides.
    share_pct: Mapped[float] = mapped_column(Numeric(7, 4), default=0.0)

    # Dollar amount allocated to this rider.
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0)

    status: Mapped[RiderDividendShareStatus] = mapped_column(
        SAEnum(RiderDividendShareStatus),
        default=RiderDividendShareStatus.pending,
        nullable=False,
        index=True,
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    membership = relationship("RiderCoopMembership", back_populates="dividend_shares")
    rider = relationship("User", foreign_keys=[rider_id])
