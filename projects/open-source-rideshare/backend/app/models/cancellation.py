"""Models for the ride cancellation policy and fee system.

Two tables:

  CancellationPolicy  — platform-level configuration (singleton, admin-managed).
                        Only one policy is active at a time; old policies are
                        preserved for audit purposes.

  CancellationRecord  — one row per cancelled ride recording who cancelled,
                        whether the grace period had expired, and the fee outcome.

Fee logic (applied in the service layer):
  - Rider cancels within grace_period_seconds → no fee.
  - Rider cancels after grace period → rider_fee_flat + (estimated_fare * rider_fee_percent).
  - Driver cancels within driver_free_cancels_per_day → no fee.
  - Driver exceeds daily free cancels → driver_cancel_penalty.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CancelledBy(str, enum.Enum):
    """Who initiated the cancellation."""

    rider = "rider"
    driver = "driver"
    admin = "admin"
    system = "system"


class FeeChargedTo(str, enum.Enum):
    """Which party bears the cancellation fee."""

    rider = "rider"
    driver = "driver"
    none = "none"


class FeeStatus(str, enum.Enum):
    """Current state of the cancellation fee."""

    pending = "pending"
    charged = "charged"
    waived = "waived"
    refunded = "refunded"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CancellationPolicy(Base):
    """Platform-level cancellation fee configuration.

    Only one policy has is_active=True at any time. When a new policy is
    created via the admin endpoint the previous one is deactivated.
    History is preserved — rows are never deleted.

    Columns
    -------
    rider_grace_period_seconds  Seconds after booking during which a rider
                                can cancel for free.
    rider_fee_flat              Flat fee (USD) charged to rider after grace
                                period expires.
    rider_fee_percent           Additional percentage of estimated fare charged
                                to rider after grace period (e.g. 0.1000 = 10%).
                                Both flat and percent can apply simultaneously.
    driver_free_cancels_per_day Number of cancellations a driver may make per
                                calendar day at no penalty.
    driver_cancel_penalty       Penalty (USD) charged to driver for each
                                cancellation beyond the daily free limit.
    is_active                   True for the current policy.
    created_at / updated_at     Audit timestamps.
    """

    __tablename__ = "cancellation_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    rider_grace_period_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120
    )
    rider_fee_flat: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=5.00
    )
    rider_fee_percent: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.0000
    )

    driver_free_cancels_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    driver_cancel_penalty: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=2.00
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
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


class CancellationRecord(Base):
    """One record per cancelled ride.

    Created by the service layer whenever a ride is cancelled. The fee
    outcome is calculated at cancellation time and stored here for
    auditing and billing.

    Columns
    -------
    ride_id               FK → rides.id (unique: one record per ride).
    cancelled_by          Which party initiated the cancellation.
    cancellation_reason   Optional free-text reason provided by the canceller.
    cancelled_at          Timestamp of cancellation.
    grace_period_expired  True when the rider's grace window had already closed.
    fee_applied           Fee amount (USD) assessed to the cancelling party.
    fee_charged_to        Which party is billed (rider / driver / none).
    fee_status            Current billing status of the fee.
    waived_by_admin_id    Admin who waived the fee (nullable).
    waive_reason          Admin-supplied reason for waiving the fee (nullable).
    created_at            Row insertion timestamp.
    """

    __tablename__ = "cancellation_records"

    __table_args__ = (
        UniqueConstraint("ride_id", name="uq_cancellation_records_ride_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    ride_id: Mapped[int] = mapped_column(
        ForeignKey("rides.id"), nullable=False, unique=True, index=True
    )
    cancelled_by: Mapped[CancelledBy] = mapped_column(
        SAEnum(CancelledBy), nullable=False, index=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    grace_period_expired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    fee_applied: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0.00
    )
    fee_charged_to: Mapped[FeeChargedTo] = mapped_column(
        SAEnum(FeeChargedTo), nullable=False, default=FeeChargedTo.none, index=True
    )
    fee_status: Mapped[FeeStatus] = mapped_column(
        SAEnum(FeeStatus), nullable=False, default=FeeStatus.pending, index=True
    )

    waived_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    waive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    ride = relationship("Ride", foreign_keys=[ride_id])
    waived_by_admin = relationship("User", foreign_keys=[waived_by_admin_id])
