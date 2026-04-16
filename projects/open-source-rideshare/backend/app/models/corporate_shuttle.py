"""Corporate Shuttle Routes & Seat Booking models.

Enterprise accounts define fixed shuttle routes between named locations, attach
recurring schedules to each route, and allow employees to book seats on specific
run dates.

Models:
  CorporateShuttleRoute
      — a named fixed route between an origin and destination for an account
  CorporateShuttleSchedule
      — a recurring schedule (days-of-week + departure time) attached to a route
  CorporateShuttleBooking
      — a seat reservation for a specific member on a specific schedule+date

Tables:
  corporate_shuttle_routes
  corporate_shuttle_schedules
  corporate_shuttle_bookings
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ShuttleBookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    no_show = "no_show"
    completed = "completed"


class CorporateShuttleRoute(Base):
    """A named fixed shuttle route owned by a corporate account.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable route name (unique per account).
        description: Optional description.
        origin_name: Display name for the origin stop.
        origin_address: Full street address of the origin.
        origin_lat: Latitude of the origin (nullable).
        origin_lng: Longitude of the origin (nullable).
        destination_name: Display name for the destination stop.
        destination_address: Full street address of the destination.
        destination_lat: Latitude of the destination (nullable).
        destination_lng: Longitude of the destination (nullable).
        route_stops: JSON list of intermediate stops [{name, address, sequence}].
        default_capacity: Default seat count for runs on this route.
        notes: Free-text notes (nullable).
        is_active: Soft-delete flag.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shuttle_routes"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_shuttle_route_account_name"),
        Index("ix_shuttle_route_account_id", "account_id"),
        Index("ix_shuttle_route_is_active", "is_active"),
        Index("ix_shuttle_route_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    origin_name: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_address: Mapped[str] = mapped_column(String(500), nullable=False)
    origin_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    origin_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    destination_name: Mapped[str] = mapped_column(String(200), nullable=False)
    destination_address: Mapped[str] = mapped_column(String(500), nullable=False)
    destination_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    destination_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    route_stops: Mapped[list | None] = mapped_column(JSON, nullable=True)

    default_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=20)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    schedules = relationship(
        "CorporateShuttleSchedule",
        back_populates="route",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateShuttleSchedule(Base):
    """A recurring schedule for a shuttle route.

    Attributes:
        id: UUID primary key.
        route_id: FK to corporate_shuttle_routes (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        schedule_name: Human-readable schedule name (e.g., "Morning Run").
        days_of_week: JSON list of ints 0–6 (0=Monday).
        departure_time: "HH:MM" in 24h format.
        estimated_duration_minutes: Approximate run time in minutes (nullable).
        seat_capacity: Number of bookable seats per run.
        notes: Free-text notes (nullable).
        is_active: Soft-delete flag.
        created_by_id: FK to users (SET NULL).
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shuttle_schedules"
    __table_args__ = (
        Index("ix_shuttle_schedule_route_id", "route_id"),
        Index("ix_shuttle_schedule_account_id", "account_id"),
        Index("ix_shuttle_schedule_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_shuttle_routes.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    schedule_name: Mapped[str] = mapped_column(String(200), nullable=False)

    days_of_week: Mapped[list] = mapped_column(JSON, nullable=False)

    departure_time: Mapped[str] = mapped_column(String(5), nullable=False)

    estimated_duration_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    seat_capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    route = relationship(
        "CorporateShuttleRoute",
        foreign_keys=[route_id],
        back_populates="schedules",
        lazy="raise",
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    bookings = relationship(
        "CorporateShuttleBooking",
        back_populates="schedule",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateShuttleBooking(Base):
    """A seat reservation for an employee on a specific schedule run date.

    Only one active booking may exist per (schedule, member, date) combination
    (enforced via UniqueConstraint).

    Attributes:
        id: UUID primary key.
        schedule_id: FK to corporate_shuttle_schedules (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to users (SET NULL) — employee who booked the seat.
        booking_date: The specific calendar date of the run.
        status: ShuttleBookingStatus enum.
        notes: Free-text notes (nullable).
        cancelled_at: Timestamp when the booking was cancelled (nullable).
        cancelled_by_id: FK to users (SET NULL) — who cancelled.
        cancellation_reason: Optional reason string.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shuttle_bookings"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "member_id",
            "booking_date",
            name="uq_shuttle_booking_schedule_member_date",
        ),
        Index("ix_shuttle_booking_schedule_date", "schedule_id", "booking_date"),
        Index("ix_shuttle_booking_account_id", "account_id"),
        Index("ix_shuttle_booking_member_id", "member_id"),
        Index("ix_shuttle_booking_status", "status"),
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

    status: Mapped[ShuttleBookingStatus] = mapped_column(
        Enum(ShuttleBookingStatus, name="shuttlebookingstatus"),
        nullable=False,
        default=ShuttleBookingStatus.confirmed,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancelled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
        back_populates="bookings",
        lazy="raise",
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id], lazy="raise")
