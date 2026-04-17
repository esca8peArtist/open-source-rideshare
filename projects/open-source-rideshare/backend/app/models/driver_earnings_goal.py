"""Driver earnings goal model.

Each driver can set one active earnings goal (daily or weekly) used for
progress tracking in the welfare summary.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class GoalPeriodType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class DriverEarningsGoal(Base):
    """A driver's self-set earnings target for a given period."""

    __tablename__ = "driver_earnings_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    period_type: Mapped[GoalPeriodType] = mapped_column(
        Enum(GoalPeriodType), nullable=False
    )
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    driver = relationship("User", foreign_keys=[driver_id])
