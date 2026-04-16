"""Corporate Vehicle Reservation model.

Employees can reserve company fleet vehicles for self-drive use during
specified time windows — like an internal Zipcar.

Tables:
  corporate_vehicle_reservations — one record per reservation request.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ReservationStatus(str, PyEnum):
    """Status lifecycle for a vehicle reservation."""

    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"
    no_show = "no_show"


class CorporateVehicleReservation(Base):
    """An employee reservation of a corporate fleet vehicle.

    Reservations must not overlap for the same vehicle when status is
    pending or confirmed.  Admins can confirm, complete, or mark no-shows.
    Members can cancel their own reservations.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        reserved_by_id: FK to users.id (SET NULL), nullable.
        approved_by_id: FK to users.id (SET NULL), nullable — set when confirmed.
        start_time: Reservation window start (timezone-aware).
        end_time: Reservation window end (timezone-aware).
        purpose: Short description of the trip purpose.
        pickup_location: Optional pickup location text.
        dropoff_location: Optional drop-off location text.
        notes: Free-text notes.
        trip_purpose_id: FK to corporate_trip_purposes (SET NULL), nullable.
        cost_center_id: FK to corporate_cost_centers (SET NULL), nullable.
        status: Lifecycle status (pending/confirmed/cancelled/completed/no_show).
        cancelled_at: UTC timestamp when cancelled, nullable.
        cancelled_by_id: FK to users.id (SET NULL), nullable.
        cancellation_reason: Optional explanation when cancelled.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_vehicle_reservations"
    __table_args__ = (
        Index("ix_vehicle_reservations_account", "account_id"),
        Index("ix_vehicle_reservations_vehicle", "fleet_vehicle_id"),
        Index("ix_vehicle_reservations_member", "reserved_by_id"),
        Index("ix_vehicle_reservations_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    fleet_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )

    reserved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)

    pickup_location: Mapped[str | None] = mapped_column(String(300), nullable=True)

    dropoff_location: Mapped[str | None] = mapped_column(String(300), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    trip_purpose_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservationstatus"),
        nullable=False,
        default=ReservationStatus.pending,
    )

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

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    reserved_by = relationship(
        "User", foreign_keys=[reserved_by_id], lazy="raise"
    )

    approved_by = relationship(
        "User", foreign_keys=[approved_by_id], lazy="raise"
    )

    cancelled_by = relationship(
        "User", foreign_keys=[cancelled_by_id], lazy="raise"
    )
