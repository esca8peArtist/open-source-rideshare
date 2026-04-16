"""Corporate Shuttle Waitlist model.

When a shuttle schedule run is at full capacity, employees can join a waitlist
for a specific schedule and date. When a confirmed booking is cancelled the
system automatically promotes the first waiting member to a confirmed seat.

Models:
  CorporateShuttleWaitlist
      — a queued seat request for a member on a specific schedule+date

Table:
  corporate_shuttle_waitlists
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class WaitlistStatus(str, enum.Enum):
    waiting = "waiting"
    promoted = "promoted"
    expired = "expired"
    cancelled = "cancelled"


class CorporateShuttleWaitlist(Base):
    """A queued seat request for an employee on a specific schedule run date.

    Only one non-cancelled entry may exist per (schedule, member, date)
    combination (enforced via UniqueConstraint).

    Attributes:
        id: UUID primary key.
        schedule_id: FK to corporate_shuttle_schedules (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to users (SET NULL) — employee on the waitlist.
        booking_date: The specific calendar date of the run.
        status: WaitlistStatus enum (default waiting).
        queue_position: Integer position in the waitlist (1 = first in line).
        notes: Free-text notes (nullable).
        promoted_at: Timestamp when promoted to a confirmed booking (nullable).
        promoted_booking_id: FK to corporate_shuttle_bookings (SET NULL) — the
            booking created on promotion (nullable).
        cancelled_at: Timestamp when the entry was cancelled (nullable).
        cancellation_reason: Optional reason string.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shuttle_waitlists"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "member_id",
            "booking_date",
            name="uq_waitlist_schedule_member_date",
        ),
        Index("ix_waitlist_schedule_date", "schedule_id", "booking_date"),
        Index("ix_waitlist_account_id", "account_id"),
        Index("ix_waitlist_member_id", "member_id"),
        Index("ix_waitlist_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_shuttle_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    booking_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[WaitlistStatus] = mapped_column(
        Enum(WaitlistStatus, name="waitliststatus"),
        nullable=False,
        default=WaitlistStatus.waiting,
    )

    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    promoted_booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_shuttle_bookings.id", ondelete="SET NULL"),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    schedule = relationship(
        "CorporateShuttleSchedule",
        foreign_keys=[schedule_id],
        lazy="raise",
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    promoted_booking = relationship(
        "CorporateShuttleBooking",
        foreign_keys=[promoted_booking_id],
        lazy="raise",
    )
