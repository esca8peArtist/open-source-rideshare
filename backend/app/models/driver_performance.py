"""Driver performance snapshot and alert models.

Tracks periodic (weekly) KPI snapshots for each driver and raises alerts
when key metrics fall below configured thresholds. The composite score
(0-100) rolls up acceptance rate, completion rate, on-time rate, rider
rating, and a complaints penalty into a single number.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
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


class DriverPerformanceSnapshot(Base):
    """Periodic snapshot of a driver's KPI metrics.

    One record per driver per period (weekly). Recalculated on demand or
    via the bulk recalculate endpoint.  The unique constraint on
    (driver_id, period_start) ensures idempotent upserts.
    """

    __tablename__ = "driver_performance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Volume metrics
    total_rides_completed: Mapped[int] = mapped_column(Integer, default=0)
    total_rides_offered: Mapped[int] = mapped_column(Integer, default=0)
    total_rides_accepted: Mapped[int] = mapped_column(Integer, default=0)
    total_rides_cancelled_by_driver: Mapped[int] = mapped_column(Integer, default=0)

    # Rate metrics (0.0 – 1.0)
    acceptance_rate: Mapped[float] = mapped_column(Float, default=0.0)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    cancellation_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # Timing metrics
    average_pickup_time_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    on_time_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # Quality metrics
    average_rider_rating: Mapped[float] = mapped_column(Float, default=0.0)
    total_rider_ratings: Mapped[int] = mapped_column(Integer, default=0)
    total_complaints: Mapped[int] = mapped_column(Integer, default=0)

    # Composite score
    performance_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_tier: Mapped[str] = mapped_column(String(20), default="bronze")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("User", foreign_keys=[driver_id])
    alerts: Mapped[list[DriverPerformanceAlert]] = relationship(
        "DriverPerformanceAlert", back_populates="snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("driver_id", "period_start", name="uq_driver_period"),
        Index("ix_driver_performance_driver_id", "driver_id"),
        Index("ix_driver_performance_period", "period_start"),
    )


class DriverPerformanceAlert(Base):
    """Alert raised when a driver metric falls below a defined threshold.

    Alerts are tied to a specific snapshot so they can be reviewed alongside
    the full KPI context. An admin resolves them after follow-up.
    """

    __tablename__ = "driver_performance_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("driver_performance_snapshots.id"), nullable=False, index=True
    )

    # Alert classification
    alert_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # low_acceptance | high_cancellation | low_rating | low_score
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)

    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    driver = relationship("User", foreign_keys=[driver_id])
    snapshot: Mapped[DriverPerformanceSnapshot] = relationship(
        "DriverPerformanceSnapshot", back_populates="alerts"
    )
