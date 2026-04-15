"""Cooperative Board Elections.

Driver-owners elect representatives to the cooperative's board through a
formal, structured election process.  Unlike one-off proposals (DriverProposal),
board elections have:

  - Named seats with term limits and a current holder
  - A nomination window before voting opens
  - Candidate statements visible to all eligible voters
  - Admin approval of candidacies (prevents spam; admins can approve all
    legitimate candidates)
  - Secret ballots — individual choices are NOT visible outside the admin
    panel; only aggregate tallies are published after certification

Election lifecycle:
  draft → nominations_open → nominations_closed → voting_open
        → tallied → certified | cancelled

Candidacy lifecycle:
  pending → approved | rejected | withdrawn
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ElectionStatus(str, enum.Enum):
    draft = "draft"
    nominations_open = "nominations_open"
    nominations_closed = "nominations_closed"
    voting_open = "voting_open"
    tallied = "tallied"
    certified = "certified"
    cancelled = "cancelled"


class CandidacyStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CooperativeBoardSeat(Base):
    """A named seat on the cooperative's board of directors.

    Seats are created by admins and persist across elections.  Each seat
    tracks its current holder (the last certified winner).
    """

    __tablename__ = "cooperative_board_seats"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Term configuration
    term_months: Mapped[int] = mapped_column(Integer, default=12)
    max_consecutive_terms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # null = unlimited

    # Minimum rides to be eligible to run for this seat
    min_lifetime_rides_to_run: Mapped[int] = mapped_column(Integer, default=100)

    # Current holder — set when an election is certified
    current_holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_profiles.id"), nullable=True, index=True
    )
    holder_term_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    current_holder = relationship(
        "DriverProfile", foreign_keys=[current_holder_id], backref="board_seats_held"
    )
    elections = relationship("BoardElection", back_populates="seat")


class BoardElection(Base):
    """A single election for one board seat.

    One election per seat at a time.  Admin drives transitions through the
    lifecycle by calling the appropriate status-transition endpoint.
    """

    __tablename__ = "board_elections"

    id: Mapped[int] = mapped_column(primary_key=True)
    seat_id: Mapped[int] = mapped_column(
        ForeignKey("cooperative_board_seats.id"), index=True
    )

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ElectionStatus] = mapped_column(
        Enum(ElectionStatus), default=ElectionStatus.draft, index=True
    )

    # Nomination window
    nominations_open_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    nominations_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Voting window
    voting_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Eligibility
    min_lifetime_rides_to_vote: Mapped[int] = mapped_column(Integer, default=50)

    # Winner — set when election is certified
    winner_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_profiles.id"), nullable=True
    )
    certified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    certification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    seat = relationship("CooperativeBoardSeat", back_populates="elections")
    winner = relationship("DriverProfile", foreign_keys=[winner_id], backref="elections_won")
    candidacies = relationship(
        "BoardCandidacy", back_populates="election", cascade="all, delete-orphan"
    )
    votes = relationship(
        "BoardElectionVote", back_populates="election", cascade="all, delete-orphan"
    )


class BoardCandidacy(Base):
    """A driver's candidacy in a board election.

    Drivers self-nominate; admins approve or reject.  Only approved candidacies
    appear on the ballot during voting.
    """

    __tablename__ = "board_candidacies"
    __table_args__ = (
        UniqueConstraint(
            "election_id",
            "driver_profile_id",
            name="uq_board_candidacy_election_driver",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(
        ForeignKey("board_elections.id"), index=True
    )
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )

    statement: Mapped[str] = mapped_column(Text)  # Candidate's platform statement
    status: Mapped[CandidacyStatus] = mapped_column(
        Enum(CandidacyStatus), default=CandidacyStatus.pending, index=True
    )

    admin_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Optional rejection reason

    # Cached vote count — updated on each vote cast; revealed after tallying
    vote_count: Mapped[int] = mapped_column(Integer, default=0)

    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    election = relationship("BoardElection", back_populates="candidacies")
    driver_profile = relationship("DriverProfile", backref="board_candidacies")
    votes = relationship(
        "BoardElectionVote", back_populates="candidacy", cascade="all, delete-orphan"
    )


class BoardElectionVote(Base):
    """A single driver's secret ballot in a board election.

    One vote per driver per election.  The candidacy_id (who they voted for)
    is stored but only exposed in admin results — not to drivers or the public.
    """

    __tablename__ = "board_election_votes"
    __table_args__ = (
        UniqueConstraint(
            "election_id",
            "voter_driver_profile_id",
            name="uq_board_vote_election_voter",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(
        ForeignKey("board_elections.id"), index=True
    )
    candidacy_id: Mapped[int] = mapped_column(
        ForeignKey("board_candidacies.id"), index=True
    )
    voter_driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )

    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    election = relationship("BoardElection", back_populates="votes")
    candidacy = relationship("BoardCandidacy", back_populates="votes")
    voter = relationship("DriverProfile", foreign_keys=[voter_driver_profile_id], backref="election_votes_cast")
