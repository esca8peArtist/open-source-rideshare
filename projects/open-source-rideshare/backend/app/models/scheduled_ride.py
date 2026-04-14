"""Scheduled ride model.

Riders can book a ride in advance for a specific future date and time
(e.g. an airport pickup, early morning commute, event drop-off).

Lifecycle
---------
    pending          — booking created, waiting for a driver to accept
    driver_assigned  — a driver has accepted the booking
    in_progress      — the actual ride is underway
    completed        — ride finished successfully
    cancelled        — cancelled by rider, driver, or admin

When a driver *declines* a previously accepted booking the status reverts to
``pending`` so the platform can offer it to another driver.

When the scheduled time arrives (within the dispatch window), the ride is
dispatched and a linked ``Ride`` row is created.  The ``ride_id`` FK is set at
that point and the status advances to ``in_progress``.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ScheduledRideStatus(str, enum.Enum):
    PENDING = "pending"
    DRIVER_ASSIGNED = "driver_assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CancelledBy(str, enum.Enum):
    RIDER = "rider"
    DRIVER = "driver"
    ADMIN = "admin"


class ScheduledRide(Base):
    __tablename__ = "scheduled_rides"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Participants
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    # Route — stored as coordinates + human-readable addresses.
    # Geometry columns are not used here to keep the model lightweight and the
    # service layer easy to unit-test without PostGIS.
    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lon: Mapped[float] = mapped_column(Float)
    pickup_address: Mapped[str] = mapped_column(String(500))

    dropoff_lat: Mapped[float] = mapped_column(Float)
    dropoff_lon: Mapped[float] = mapped_column(Float)
    dropoff_address: Mapped[str] = mapped_column(String(500))

    # The future time the rider wants to be picked up (UTC).
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Fare estimate captured at booking time.
    estimated_fare: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optional notes from rider to driver (flight number, special instructions).
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[ScheduledRideStatus] = mapped_column(
        Enum(ScheduledRideStatus), default=ScheduledRideStatus.PENDING, index=True
    )

    # Cancellation metadata
    cancelled_by: Mapped[CancelledBy | None] = mapped_column(
        Enum(CancelledBy), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # How many times this booking was declined and returned to pending.
    decline_count: Mapped[int] = mapped_column(Integer, default=0)

    # Link to the actual Ride row once dispatch happens.
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id"), nullable=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    rider = relationship("User", foreign_keys=[rider_id], backref="scheduled_rides_as_rider")
    driver = relationship("User", foreign_keys=[driver_id], backref="scheduled_rides_as_driver")
