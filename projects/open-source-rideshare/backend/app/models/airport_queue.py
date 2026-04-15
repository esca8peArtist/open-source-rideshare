"""Airport queue management models.

Airports impose strict rules on how rideshare drivers may wait for
passengers.  Drivers must stage in a designated holding lot and are
dispatched FIFO when a pickup request arrives at a terminal.

This module models:
  AirportZone   — a physical airport staging/pickup zone configured
                  by platform admins.  Holds capacity and policy info.
  AirportQueueEntry — one row per driver-per-zone queue slot.

Entry lifecycle:
  waiting → dispatched   (admin/system dispatches next driver)
  waiting → left         (driver self-removes before dispatch)
  waiting → expired      (TTL exceeded without dispatch)

Design notes:
  - Unique constraint (zone_id, driver_id) prevents a driver from
    joining the same zone twice.
  - position is maintained in-memory / at query time by ordering
    joined_at; we do not store a mutable position column to avoid
    race conditions.
  - Dispatched/left/expired entries are kept for analytics.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class QueueEntryStatus(str, enum.Enum):
    waiting = "waiting"
    dispatched = "dispatched"
    left = "left"
    expired = "expired"


class AirportZone(Base):
    """A physical airport staging area or pickup zone.

    Admins create one row per terminal / staging lot combination.
    max_queue_size caps how many drivers may wait simultaneously.
    A zone that is_active=False stops accepting new entries but
    retains its historical queue records.
    """

    __tablename__ = "airport_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    airport_code: Mapped[str] = mapped_column(String(10), nullable=False)
    terminal: Mapped[str | None] = mapped_column(String(60), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_queue_size: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    # Minutes a driver may remain at the head of the queue before expiry
    ttl_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    entries: Mapped[list[AirportQueueEntry]] = relationship(
        "AirportQueueEntry", back_populates="zone", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_airport_zones_airport_code", "airport_code"),
        Index("ix_airport_zones_is_active", "is_active"),
    )


class AirportQueueEntry(Base):
    """One driver waiting (or previously waited) in an airport zone queue.

    Ordering by joined_at ASC within a zone gives the FIFO queue
    position.  Only entries with status='waiting' represent the live
    queue.
    """

    __tablename__ = "airport_queue_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    zone_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("airport_zones.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[QueueEntryStatus] = mapped_column(
        Enum(QueueEntryStatus, name="queueentrystatus"),
        default=QueueEntryStatus.waiting,
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    zone: Mapped[AirportZone] = relationship("AirportZone", back_populates="entries")
    driver: Mapped["User"] = relationship("User", foreign_keys=[driver_id])  # noqa: F821

    __table_args__ = (
        # A driver may only have ONE active (waiting) entry per zone
        UniqueConstraint("zone_id", "driver_id", name="uq_airport_queue_zone_driver"),
        Index("ix_airport_queue_zone_status", "zone_id", "status"),
        Index("ix_airport_queue_driver_status", "driver_id", "status"),
    )
