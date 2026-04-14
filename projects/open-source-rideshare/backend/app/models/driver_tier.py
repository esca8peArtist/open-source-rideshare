"""Driver career tier model.

Tracks a driver's cumulative achievement tier earned over their lifetime on the
platform.  Separate from the per-period ``score_tier`` on DriverPerformanceSnapshot,
which reflects short-term weekly KPIs.

Career tiers are permanent achievements that rise with experience, rating, and
reliability.  They unlock dispatch-priority bonuses and earnings multipliers to
reward long-tenured, high-quality drivers.

Tier thresholds (all three criteria must be met to qualify):

  BRONZE   — default for all drivers (0+ rides, any rating)
  SILVER   — 50+ lifetime rides, 4.5+ avg rating, 80%+ acceptance rate
  GOLD     — 200+ lifetime rides, 4.7+ avg rating, 85%+ acceptance rate
  PLATINUM — 500+ lifetime rides, 4.8+ avg rating, 90%+ acceptance rate

Tier is stored in ``driver_career_tiers`` (one row per driver, created on first
evaluation or first ``/drivers/me/tier`` request).  The service recalculates and
updates the row whenever a refresh is triggered.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CareerTierLevel(str, enum.Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class DriverCareerTier(Base):
    """Persistent career tier record for a driver.

    One row per driver.  Created with BRONZE on first access; updated in-place
    when a recalculation changes the tier.

    Columns
    -------
    driver_id        FK to driver_profiles.id (unique — one row per driver)
    current_tier     Enum: bronze | silver | gold | platinum
    previous_tier    The tier before the most recent change (None if never changed)
    tier_since       Timestamp of the most recent tier change
    evaluated_at     Timestamp of the most recent recalculation (even if no change)
    snapshot_rides   Lifetime ride count used in the most recent evaluation
    snapshot_rating  Avg rating used in the most recent evaluation
    snapshot_acceptance_rate  Acceptance rate used in the most recent evaluation
    """

    __tablename__ = "driver_career_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    current_tier: Mapped[CareerTierLevel] = mapped_column(
        Enum(CareerTierLevel, name="career_tier_level"),
        default=CareerTierLevel.BRONZE,
        nullable=False,
    )
    previous_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)

    tier_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Metric snapshot captured at evaluation time
    snapshot_rides: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshot_rating: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    snapshot_acceptance_rate: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False
    )

    driver = relationship("DriverProfile", backref="career_tier")
