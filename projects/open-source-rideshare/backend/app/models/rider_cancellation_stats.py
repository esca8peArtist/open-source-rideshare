"""Rider cancellation statistics model.

One row per rider, updated whenever the rider cancels a ride.
Tracks lifetime totals so cancel rate can be assessed quickly without
a full table scan of rides.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.ride import CancellationCategory


class RiderCancellationStats(Base):
    """Aggregate cancellation metrics for a single rider.

    Updated in a fire-and-forget fashion each time the rider cancels a ride.
    ``total_rides_requested`` is incremented when a ride is requested so the
    cancel rate denominator stays accurate.
    """

    __tablename__ = "rider_cancellation_stats"
    __table_args__ = (UniqueConstraint("rider_id", name="uq_rider_cancel_stats_rider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Volume counters
    total_rides_requested: Mapped[int] = mapped_column(Integer, default=0)
    total_cancellations: Mapped[int] = mapped_column(Integer, default=0)
    cancellations_in_grace_period: Mapped[int] = mapped_column(Integer, default=0)
    cancellations_with_fee: Mapped[int] = mapped_column(Integer, default=0)

    # Rate (0.0 – 1.0)  recalculated on every update
    cancellation_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # Most recent cancellation metadata
    last_cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cancel_category: Mapped[CancellationCategory | None] = mapped_column(
        Enum(CancellationCategory), nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    rider = relationship("User", foreign_keys=[rider_id], backref="cancellation_stats")
