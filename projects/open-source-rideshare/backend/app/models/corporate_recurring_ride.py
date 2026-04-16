"""Corporate Recurring Ride Schedule models.

Employees configure personal recurring ride schedules (daily commute,
weekly airport transfer, monthly off-site meetings) that track their
standing transportation needs.  Each schedule generates booking records
that capture when a ride was requested and whether it succeeded.

Models:
  CorporateRecurringRide
      — a named recurring-ride schedule owned by one corporate member
  CorporateRecurringRideBooking
      — an immutable log entry for each scheduled booking attempt

Table names:
  corporate_recurring_rides
  corporate_recurring_ride_bookings
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class RecurrenceType(str, enum.Enum):
    """How often a recurring ride is scheduled."""

    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class RecurringRideBookingStatus(str, enum.Enum):
    """Status of a single recurring-ride booking attempt."""

    pending = "pending"
    booked = "booked"
    failed = "failed"
    skipped = "skipped"


class CorporateRecurringRide(Base):
    """A named recurring-ride schedule owned by one corporate employee.

    The schedule captures the routing and timing preferences for a
    standing trip.  ``recurrence_type`` determines which scheduling
    fields are relevant:

    * ``daily``   — fires every calendar day at ``scheduled_time``.
    * ``weekly``  — fires on the days listed in ``days_of_week``
                    (0 = Monday … 6 = Sunday) at ``scheduled_time``.
    * ``monthly`` — fires on ``day_of_month`` of every month at
                    ``scheduled_time``.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to corporate_account_members (CASCADE delete).
        name: Human-readable schedule name, unique per member+account pair.
        pickup_address: Street address for pickup.
        pickup_lat / pickup_lng: Geocoordinate for pickup.
        dropoff_address: Street address for dropoff.
        dropoff_lat / dropoff_lng: Geocoordinate for dropoff.
        vehicle_type: Preferred vehicle class (nullable = any).
        recurrence_type: ``daily``, ``weekly``, or ``monthly``.
        days_of_week: JSONB list of ints 0–6 (Monday–Sunday).
            Only relevant for ``weekly`` recurrence.
        day_of_month: Calendar day 1–31 for ``monthly`` recurrence.
        scheduled_time: "HH:MM" string in the employee's local time.
        advance_booking_minutes: How many minutes before ``scheduled_time``
            to create the booking (e.g. 30 = book 30 min ahead of ride time).
        cost_center_id: Optional FK to corporate_cost_centers (SET NULL).
        trip_purpose_id: Optional FK to corporate_trip_purposes (SET NULL).
        notes: Freeform instructions for the driver / booking system.
        is_active: Soft-disable; inactive schedules are not processed.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_recurring_rides"
    __table_args__ = (
        Index("ix_corp_recurring_ride_account_id", "account_id"),
        Index("ix_corp_recurring_ride_member_id", "member_id"),
        Index("ix_corp_recurring_ride_account_member", "account_id", "member_id"),
        Index("ix_corp_recurring_ride_account_active", "account_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Pickup location
    pickup_address: Mapped[str] = mapped_column(String(500), nullable=False)
    pickup_lat: Mapped[sa.Numeric | None] = mapped_column(
        sa.Numeric(9, 6), nullable=True
    )
    pickup_lng: Mapped[sa.Numeric | None] = mapped_column(
        sa.Numeric(9, 6), nullable=True
    )

    # Dropoff location
    dropoff_address: Mapped[str] = mapped_column(String(500), nullable=False)
    dropoff_lat: Mapped[sa.Numeric | None] = mapped_column(
        sa.Numeric(9, 6), nullable=True
    )
    dropoff_lng: Mapped[sa.Numeric | None] = mapped_column(
        sa.Numeric(9, 6), nullable=True
    )

    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    recurrence_type: Mapped[RecurrenceType] = mapped_column(
        Enum(RecurrenceType, name="recurrencetype"), nullable=False
    )

    # weekly: list of day numbers 0–6
    days_of_week: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # monthly: day of month 1–31
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # "HH:MM" string, employee-local time
    scheduled_time: Mapped[str] = mapped_column(String(5), nullable=False)

    advance_booking_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )

    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
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
    member = relationship(
        "User", foreign_keys=[member_id], lazy="raise"
    )
    bookings = relationship(
        "CorporateRecurringRideBooking",
        back_populates="recurring_ride",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateRecurringRideBooking(Base):
    """An immutable log entry for a single recurring-ride booking attempt.

    Created each time the scheduling system attempts to book a ride for a
    ``CorporateRecurringRide``.  The ``ride_id`` is populated when the
    booking succeeds; ``failure_reason`` is populated when it fails.

    Attributes:
        id: UUID primary key.
        recurring_ride_id: FK to corporate_recurring_rides (CASCADE delete).
        account_id: Denormalised FK for efficient account-scoped queries.
        member_id: Denormalised FK for efficient member-scoped queries.
        ride_id: FK to rides (SET NULL) — linked ride when booked successfully.
        scheduled_for: The datetime for which the ride was scheduled.
        status: ``pending`` / ``booked`` / ``failed`` / ``skipped``.
        failure_reason: Human-readable explanation when status is ``failed``.
        created_at: UTC timestamp when the booking attempt was recorded.
    """

    __tablename__ = "corporate_recurring_ride_bookings"
    __table_args__ = (
        Index("ix_corp_rrb_recurring_ride_id", "recurring_ride_id"),
        Index("ix_corp_rrb_account_id", "account_id"),
        Index("ix_corp_rrb_account_scheduled", "account_id", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    recurring_ride_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_recurring_rides.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
    )

    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    status: Mapped[RecurringRideBookingStatus] = mapped_column(
        Enum(RecurringRideBookingStatus, name="recurringrridebookingstatus"),
        nullable=False,
        default=RecurringRideBookingStatus.pending,
    )

    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    recurring_ride = relationship(
        "CorporateRecurringRide",
        foreign_keys=[recurring_ride_id],
        back_populates="bookings",
        lazy="raise",
    )
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
