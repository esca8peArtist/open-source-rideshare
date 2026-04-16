"""Corporate Event models.

Enterprise coordinators organize company events (team offsites, conferences,
client dinners, holiday parties), invite employees, and link rides for
consolidated billing.

Tables:
  corporate_events           — one row per corporate event.
  corporate_event_attendees  — junction table linking members (and rides) to events.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateEvent(Base):
    """A corporate event that groups employee rides for consolidated billing.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        organizer_id: FK to users — employee who is the event organizer
            (SET NULL on user deletion).
        created_by_id: FK to users — employee who created the event record
            (SET NULL on user deletion).
        title: Human-readable event name.
        description: Optional longer description of the event.
        event_location_name: Name of the venue or location.
        event_address_line1: Optional street address line.
        event_city: Optional city.
        event_state: Optional state/province.
        event_country: Optional country code, defaults to "US".
        event_latitude: Optional latitude for geo lookups.
        event_longitude: Optional longitude for geo lookups.
        corporate_address_id: Optional FK to corporate_addresses (SET NULL).
        event_datetime: Date and time of the event.
        status: Lifecycle state — draft / active / completed / cancelled.
            Stored as a plain string (not a PG enum type) for flexibility.
        budget_usd: Optional total budget for the event.
        max_attendees: Optional cap on attendee count.
        auto_approve_rides: When True, rides linked to this event are
            automatically approved.
        notes: Optional internal notes.
        is_active: When False the event is hidden from default list views.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_events"
    __table_args__ = (
        Index("ix_corp_event_account_id", "account_id"),
        Index("ix_corp_event_account_status", "account_id", "status"),
        Index("ix_corp_event_account_datetime", "account_id", "event_datetime"),
        Index("ix_corp_event_created_by", "created_by_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    organizer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_location_name: Mapped[str] = mapped_column(String(200), nullable=False)

    event_address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)

    event_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    event_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    event_country: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default="US"
    )

    event_latitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    event_longitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    corporate_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_addresses.id", ondelete="SET NULL"),
        nullable=True,
    )

    event_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Stored as String — not a PG enum type — so we can add values without migrations.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )

    budget_usd: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    max_attendees: Mapped[int | None] = mapped_column(Integer, nullable=True)

    auto_approve_rides: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    organizer = relationship("User", foreign_keys=[organizer_id], lazy="raise")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")


class CorporateEventAttendee(Base):
    """An attendee record linking a member (and optionally a ride) to an event.

    SET NULL on user or ride deletion so the association record persists even
    after the user or ride row is removed — useful for audit history.

    Attributes:
        id: Integer primary key.
        event_id: FK to corporate_events (CASCADE delete).
        member_id: FK to users — the attending employee (SET NULL on deletion).
        ride_id: FK to rides — linked ride for consolidated billing (SET NULL).
        invited_by_id: FK to users — who sent the invitation (SET NULL).
        status: Attendee lifecycle state — invited / confirmed / declined / cancelled.
        notes: Optional note about this attendee.
        created_at: When the attendee record was created.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_event_attendees"
    __table_args__ = (
        UniqueConstraint("event_id", "member_id", name="uq_event_attendee"),
        Index("ix_corp_event_attendee_event", "event_id"),
        Index("ix_corp_event_attendee_member", "member_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    event_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_events.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
    )

    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Stored as String — not a PG enum type — so we can add values without migrations.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    event = relationship("CorporateEvent", foreign_keys=[event_id], lazy="raise")
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    ride = relationship("Ride", foreign_keys=[ride_id], lazy="raise")
    invited_by = relationship("User", foreign_keys=[invited_by_id], lazy="raise")
