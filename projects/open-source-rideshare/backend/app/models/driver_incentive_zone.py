"""Driver Incentive Zone models.

Transparent "boost zones" — admin-created geographic windows where drivers earn
bonus compensation for completing rides.  Unlike Uber's opaque Boost multipliers,
every zone includes a human-readable reason so drivers and the community
understand why the coop is offering the incentive.

Two bonus structures are supported:
  MULTIPLIER — earnings are scaled by a factor (e.g. 1.5× for 90-minute window)
  FLAT       — a fixed dollar bonus is added per completed qualifying ride

Tables:
  driver_incentive_zones      — zone definitions (admin-managed)
  driver_zone_completions     — per-ride bonus records (idempotent)
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class IncentiveBonusType(str, enum.Enum):
    multiplier = "multiplier"  # earnings × multiplier (e.g. 1.5)
    flat = "flat"              # fixed bonus in cents per qualifying ride


class DriverIncentiveZone(Base):
    """Admin-defined geographic zone with an earnings bonus window."""

    __tablename__ = "driver_incentive_zones"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Why the coop is offering this incentive (cooperative transparency).
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Geographic definition — polygon OR circle (polygon takes precedence).
    polygon: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="List of {lat, lon} dicts defining the zone boundary.",
    )
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Bonus configuration.
    bonus_type: Mapped[IncentiveBonusType] = mapped_column(
        Enum(IncentiveBonusType), nullable=False
    )
    # For MULTIPLIER type: earnings × bonus_multiplier (must be > 1.0).
    bonus_multiplier: Mapped[float | None] = mapped_column(
        Numeric(5, 3), nullable=True
    )
    # For FLAT type: bonus in US cents per qualifying ride.
    bonus_flat_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Time window — absolute datetimes (timezone-aware).
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Optional caps to prevent budget overruns.
    max_total_completions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_completions_per_driver: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Minimum driver rating required to earn the bonus.
    min_driver_rating: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    completions = relationship(
        "DriverZoneCompletion", back_populates="zone", cascade="all, delete-orphan"
    )


class DriverZoneCompletion(Base):
    """Immutable record of a driver earning a zone bonus on a specific ride.

    Idempotent: the (zone_id, ride_id) unique constraint prevents double-awarding
    the same bonus for the same ride.
    """

    __tablename__ = "driver_zone_completions"

    id: Mapped[int] = mapped_column(primary_key=True)

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("driver_incentive_zones.id"), index=True
    )
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )
    ride_id: Mapped[int] = mapped_column(Integer, index=True)

    # Bonus actually awarded (cents).
    bonus_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshot of which type was applied at award time.
    bonus_type: Mapped[IncentiveBonusType] = mapped_column(
        Enum(IncentiveBonusType), nullable=False
    )

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "zone_id",
            "ride_id",
            name="uq_driver_zone_completions_zone_ride",
        ),
    )

    zone = relationship("DriverIncentiveZone", back_populates="completions")
    driver_profile = relationship("DriverProfile", backref="zone_completions")
