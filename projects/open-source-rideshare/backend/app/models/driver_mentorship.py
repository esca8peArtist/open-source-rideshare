"""Driver Mentorship Program models.

Cooperative differentiator — experienced drivers mentor new ones and earn a
small commission on mentee rides for a configurable number of days.  Uber and
Lyft provide no formal mentorship infrastructure; this builds driver community
and reduces early-driver attrition.

Tables:
  driver_mentorships    — one active mentorship per mentee at a time
  mentorship_earnings   — commission earned per ride by the mentor

Mentorship lifecycle:
  pending   — new driver requested mentorship; awaiting admin assignment
  active    — mentor assigned; commission clock running
  completed — commission period ended naturally (days elapsed)
  cancelled — admin or participant cancelled early

Commission is calculated per completed ride:
  mentor_earnings = mentee_ride_earnings * commission_rate
  Default: 2% for 90 days.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
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


class MentorshipStatus(str, enum.Enum):
    pending = "pending"        # Awaiting mentor assignment
    active = "active"          # Mentor assigned, commission running
    completed = "completed"    # Commission period ended naturally
    cancelled = "cancelled"    # Cancelled by admin or participant


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DriverMentorship(Base):
    """A mentorship pairing between an experienced driver (mentor) and a new
    driver (mentee).

    Business rules:
      - A mentee may only have one active or pending mentorship at a time.
      - starts_at / ends_at are set when the mentor is assigned.
      - commission_rate and commission_days snapshot the policy at assignment
        time so future policy changes don't affect active mentorships.
    """

    __tablename__ = "driver_mentorships"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The new driver seeking guidance.
    mentee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # The experienced driver providing guidance.  Null until admin assigns.
    mentor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    status: Mapped[MentorshipStatus] = mapped_column(
        SAEnum(MentorshipStatus, name="mentorshipstatus"),
        default=MentorshipStatus.pending,
        nullable=False,
        index=True,
    )

    # Snapshotted at assignment time.
    commission_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.02, comment="Fraction of mentee ride earnings"
    )
    commission_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )

    # Set when mentor is assigned.
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Optional note from admin when assigning.
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    mentee = relationship("User", foreign_keys=[mentee_id])
    mentor = relationship("User", foreign_keys=[mentor_id])
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
    earnings = relationship("MentorshipEarning", back_populates="mentorship")

    __table_args__ = (
        # Prevent a mentee from having two simultaneous active/pending mentorships.
        UniqueConstraint(
            "mentee_id",
            name="uq_mentorship_active_mentee",
            # Enforced by service layer for active/pending; partial index on DB
            # would require DB-specific syntax so we rely on service checks.
        ),
    )


class MentorshipEarning(Base):
    """Commission earned by a mentor for one completed mentee ride.

    Immutable once created.  Linked to a ride so that payout processing can
    roll up commissions alongside normal driver earnings.
    """

    __tablename__ = "mentorship_earnings"

    id: Mapped[int] = mapped_column(primary_key=True)

    mentorship_id: Mapped[int] = mapped_column(
        ForeignKey("driver_mentorships.id"), nullable=False, index=True
    )

    # The ride that generated this earning.
    ride_id: Mapped[int] = mapped_column(
        ForeignKey("rides.id"), nullable=False, index=True
    )

    # The mentee's earnings for the ride (base for commission calculation).
    mentee_earnings: Mapped[float] = mapped_column(Float, nullable=False)

    # Actual commission credited to the mentor.
    commission_amount: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Null until included in a mentor payout run.
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    mentorship = relationship("DriverMentorship", back_populates="earnings")

    __table_args__ = (
        # One earning record per ride per mentorship (idempotency).
        UniqueConstraint("mentorship_id", "ride_id", name="uq_mentorship_earning_ride"),
    )
