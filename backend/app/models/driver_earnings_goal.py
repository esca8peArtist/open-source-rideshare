"""Driver earnings goal model.

Each driver may have at most one active goal (one row per driver).
The goal specifies a target earnings amount for a recurring daily or
weekly period.  Progress is computed on-demand from the rides/payment
tables — no per-period state is stored here.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class GoalPeriodType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class DriverEarningsGoal(Base):
    """A driver's self-set earnings target.

    Columns
    -------
    driver_profile_id  FK to driver_profiles.id (unique — one goal per driver)
    period_type        Whether the target resets daily or weekly
    target_amount      USD target for the period (> 0, ≤ 2 000)
    created_at         When the goal was first set
    updated_at         When the goal was last modified
    """

    __tablename__ = "driver_earnings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    period_type: Mapped[GoalPeriodType] = mapped_column(
        Enum(GoalPeriodType, name="goalperiodtype"),
        nullable=False,
        default=GoalPeriodType.DAILY,
    )
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("DriverProfile", backref="earnings_goal")
