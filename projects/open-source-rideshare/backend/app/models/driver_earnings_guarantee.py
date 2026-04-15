"""Driver minimum earnings guarantee models.

A cooperative rideshare platform guarantees that driver-members earn at least
a minimum amount per completed ride. When a driver's weekly gross earnings fall
below the guaranteed floor, the platform pays the shortfall from the cooperative
surplus — ensuring drivers are never exploited by slow weeks or system issues.

Policy
------
Admin configures a per-ride floor and a minimum rides threshold:
  minimum_per_ride_usd     — floor earned per completed ride (e.g. $10.00)
  minimum_rides_to_qualify — driver must reach this count to be eligible

Weekly Records
--------------
After each week admin runs `process_week`, which creates one WeeklyGuaranteeRecord
per driver who completed at least one ride. Drivers below the threshold are marked
`ineligible`; those above the threshold with gross ≥ guaranteed are `waived`;
those with a shortfall are `pending` until admin pays them (→ `paid`).

Status flow:
  WeeklyGuaranteeRecord:  ineligible  (driver didn't meet threshold)
                           waived      (no shortfall — earnings OK)
                           pending  →  paid
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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

class GuaranteeStatus(str, enum.Enum):
    ineligible = "ineligible"   # didn't meet minimum rides threshold
    waived = "waived"           # earnings met or exceeded guarantee — no payout needed
    pending = "pending"         # shortfall owed, awaiting payment
    paid = "paid"               # shortfall has been paid out


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EarningsGuaranteePolicy(Base):
    """Platform-level configuration for the minimum earnings guarantee.

    Only one policy is active at a time. Creating a new policy deactivates
    the previous one. History is preserved (rows are never deleted).

    Columns
    -------
    minimum_per_ride_usd      Floor earnings per completed ride
    minimum_rides_to_qualify  Minimum rides per week to be eligible for the guarantee
    effective_from            Date from which this policy applies
    effective_until           Date after which this policy no longer applies (None = open-ended)
    is_active                 True for the current active policy
    notes                     Optional admin rationale
    created_by_user_id        Admin who created/updated the policy
    """

    __tablename__ = "earnings_guarantee_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    minimum_per_ride_usd: Mapped[float] = mapped_column(
        Numeric(8, 2), nullable=False, default=10.00
    )
    minimum_rides_to_qualify: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    weekly_records = relationship(
        "WeeklyGuaranteeRecord",
        back_populates="policy",
        cascade="all, delete-orphan",
    )


class WeeklyGuaranteeRecord(Base):
    """Per-driver weekly guarantee calculation and payout record.

    One row per (driver, week_start). Idempotent: running process_week
    again for the same week updates existing records rather than duplicating.

    Columns
    -------
    driver_id               FK → users.id
    driver_profile_id       FK → driver_profiles.id
    week_start              ISO Monday of the week (e.g. 2026-04-13)
    week_end                ISO Sunday of the week (e.g. 2026-04-19)
    policy_id               The policy used for this calculation
    rides_completed         Total rides completed during the week
    gross_earnings_usd      Actual earnings from rides (before guarantee)
    guaranteed_earnings_usd rides_completed * minimum_per_ride_usd
    shortfall_usd           max(0, guaranteed_earnings_usd - gross_earnings_usd)
    status                  ineligible / waived / pending / paid
    paid_at                 When the shortfall was paid (if applicable)
    processed_at            When the record was last calculated/updated
    """

    __tablename__ = "weekly_guarantee_records"

    __table_args__ = (
        UniqueConstraint(
            "driver_id", "week_start",
            name="uq_weekly_guarantee_driver_week",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), nullable=False, index=True
    )
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("earnings_guarantee_policies.id"), nullable=False, index=True
    )

    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)

    rides_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gross_earnings_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    guaranteed_earnings_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    shortfall_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)

    status: Mapped[GuaranteeStatus] = mapped_column(
        SAEnum(GuaranteeStatus),
        nullable=False,
        default=GuaranteeStatus.pending,
        index=True,
    )

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    policy = relationship("EarningsGuaranteePolicy", back_populates="weekly_records")
    driver = relationship("User", foreign_keys=[driver_id])
    driver_profile = relationship("DriverProfile", foreign_keys=[driver_profile_id])
