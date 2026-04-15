"""Corporate batch/group booking models.

Companies can create a batch booking (draft), add individual ride requests,
then submit the batch for fulfilment.  This enables event shuttles, offsites,
and airport pickups for multiple passengers in one coordinated operation.

CorporateBatchBooking      — table corporate_batch_bookings
CorporateBatchRideRequest  — table corporate_batch_ride_requests
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class BatchBookingStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class BatchRideRequestStatus(str, enum.Enum):
    PENDING = "pending"
    REMOVED = "removed"


class CorporateBatchBooking(Base):
    """A batch (group) booking for a corporate account.

    Attributes:
        account_id: FK to corporate_accounts_v2.
        name: Human-readable label, e.g. "Q2 Sales Offsite Shuttles".
        event_date: Optional date the event/rides take place.
        notes: Optional free-text notes visible to account admins.
        status: Workflow state — draft → submitted (or any → cancelled).
        created_by_user_id: FK to the user who created this batch.
        submitted_at: When the batch was submitted.
        cancelled_at: When the batch was cancelled.
        cancellation_reason: Optional reason provided at cancellation.
        created_at: Row creation timestamp.
        updated_at: Row last-modification timestamp.
    """

    __tablename__ = "corporate_batch_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="account_id",
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[BatchBookingStatus] = mapped_column(
        SAEnum(BatchBookingStatus, name="batchbookingstatus"),
        nullable=False,
        default=BatchBookingStatus.DRAFT,
        index=True,
    )

    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(
        String(300), nullable=True
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

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    ride_requests: Mapped[list[CorporateBatchRideRequest]] = relationship(
        "CorporateBatchRideRequest",
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class CorporateBatchRideRequest(Base):
    """A single ride within a corporate batch booking.

    Attributes:
        batch_id: FK to corporate_batch_bookings.
        account_id: Denormalised FK to corporate_accounts_v2 for fast account-scoped queries.
        passenger_name: Full name of the passenger.
        passenger_email: Optional contact email.
        passenger_phone: Optional contact phone number.
        pickup_address: Human-readable pickup address.
        pickup_lat: Optional latitude for the pickup location.
        pickup_lng: Optional longitude for the pickup location.
        dropoff_address: Human-readable drop-off address.
        dropoff_lat: Optional latitude for the drop-off location.
        dropoff_lng: Optional longitude for the drop-off location.
        requested_time: When the ride should start (tz-aware).
        notes: Optional free-text notes for this specific ride.
        status: PENDING or REMOVED.
        added_at: When this request was added to the batch.
    """

    __tablename__ = "corporate_batch_ride_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_batch_bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id"),
        nullable=False,
        index=True,
    )

    passenger_name: Mapped[str] = mapped_column(String(150), nullable=False)
    passenger_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    passenger_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    pickup_address: Mapped[str] = mapped_column(String(300), nullable=False)
    pickup_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    pickup_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    dropoff_address: Mapped[str] = mapped_column(String(300), nullable=False)
    dropoff_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    dropoff_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    requested_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status: Mapped[BatchRideRequestStatus] = mapped_column(
        SAEnum(BatchRideRequestStatus, name="batchridequeststatus"),
        nullable=False,
        default=BatchRideRequestStatus.PENDING,
        index=True,
    )

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    batch: Mapped[CorporateBatchBooking] = relationship(
        "CorporateBatchBooking", back_populates="ride_requests"
    )
