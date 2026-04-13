"""Incentive and bonus program models.

Supports quest bonuses, peak-hour per-trip bonuses, streak bonuses,
and earnings guarantees — similar to Uber/Lyft driver quests.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ProgramType(str, enum.Enum):
    QUEST = "quest"
    PEAK_HOURS = "peak_hours"
    STREAK = "streak"
    EARNINGS_GUARANTEE = "earnings_guarantee"


class ProgressStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAID = "paid"
    EXPIRED = "expired"


class IncentiveProgram(Base):
    """Admin-defined bonus program (quest, peak hours, streak, earnings guarantee)."""

    __tablename__ = "incentive_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default="")
    program_type: Mapped[str] = mapped_column(String(50))  # ProgramType values

    # Bonus amount meaning depends on program_type:
    #   quest/streak: flat payout on completion
    #   peak_hours: per-trip bonus amount
    #   earnings_guarantee: guaranteed floor for the period
    bonus_amount: Mapped[float]

    # trips required (quest) or streak length (streak); None for others
    trip_target: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Time-of-day window (used by quest and peak_hours)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Date range for program validity
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Comma-separated day-of-week ints: "0,1,2,3,4" (Mon=0). None = all days.
    days_of_week: Mapped[str | None] = mapped_column(String(20), nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    progress_records: Mapped[list[DriverIncentiveProgress]] = relationship(
        "DriverIncentiveProgress", back_populates="program"
    )


class DriverIncentiveProgress(Base):
    """Tracks each driver's progress toward a specific incentive program."""

    __tablename__ = "driver_incentive_progress"
    __table_args__ = (
        UniqueConstraint("driver_id", "program_id", "period_start", name="uq_driver_program_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("incentive_programs.id"), index=True)

    trips_completed: Mapped[int] = mapped_column(Integer, default=0)
    bonus_earned: Mapped[float] = mapped_column(default=0.0)  # Total bonus paid out from this entry

    status: Mapped[str] = mapped_column(String(50), default=ProgressStatus.ACTIVE.value)

    period_start: Mapped[date] = mapped_column(Date)  # Which day this progress entry covers

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    driver: Mapped["User"] = relationship("User")  # type: ignore[name-defined]  # noqa: F821
    program: Mapped[IncentiveProgram] = relationship("IncentiveProgram", back_populates="progress_records")
