"""Cooperative member dividend / profit-sharing models.

When the platform generates surplus (platform fees minus operating costs),
driver-members receive a proportional share based on rides completed in the
period. This is the financial heart of the cooperative — driver-owners share
in the platform's success.

Lifecycle:
  CooperativeDividend:  pending → approved → distributed
                        pending/approved → cancelled

  DriverDividendShare:  pending → paid  (when parent is distributed)
                        pending → cancelled (when parent is cancelled)

Shares are calculated at declaration time:
  per_ride_payout_usd = total_platform_surplus_usd / total_qualifying_rides
  driver_amount_usd   = driver_qualifying_rides * per_ride_payout_usd
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DividendStatus(str, enum.Enum):
    pending = "pending"        # declared but not yet approved
    approved = "approved"      # approved for distribution
    distributed = "distributed"  # all shares paid out
    cancelled = "cancelled"    # cancelled before distribution


class DividendShareStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    cancelled = "cancelled"


class CooperativeDividend(Base):
    """A quarterly profit-sharing distribution declared by admin.

    Represents a single distribution event for a given (year, quarter).
    """

    __tablename__ = "cooperative_dividends"
    __table_args__ = (
        UniqueConstraint("year", "quarter", name="uq_cooperative_dividend_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4

    # The amount to distribute among all qualifying driver-members.
    total_platform_surplus_usd: Mapped[float] = mapped_column(Numeric(12, 2), default=0.0)

    # Denominator used in share calculation — total rides across all drivers
    # during this quarter (used to split the surplus proportionally).
    total_qualifying_rides: Mapped[int] = mapped_column(Integer, default=0)

    # Per-ride payout = total_platform_surplus_usd / total_qualifying_rides.
    # 0.0 when total_qualifying_rides == 0 (no distribution possible).
    per_ride_payout_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0.0)

    status: Mapped[DividendStatus] = mapped_column(
        SAEnum(DividendStatus), default=DividendStatus.pending, nullable=False, index=True
    )

    # Admin who approved the distribution (null until approved).
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    distributed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    approved_by = relationship("User", foreign_keys=[approved_by_user_id])
    shares = relationship(
        "DriverDividendShare",
        back_populates="dividend",
        cascade="all, delete-orphan",
    )


class DriverDividendShare(Base):
    """A single driver's allocation within a cooperative dividend distribution."""

    __tablename__ = "driver_dividend_shares"

    id: Mapped[int] = mapped_column(primary_key=True)

    dividend_id: Mapped[int] = mapped_column(
        ForeignKey("cooperative_dividends.id"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), nullable=False, index=True
    )

    # Rides this driver completed in the distribution quarter.
    qualifying_rides: Mapped[int] = mapped_column(Integer, default=0)

    # Driver's share as a percentage of total qualifying rides.
    share_pct: Mapped[float] = mapped_column(Numeric(7, 4), default=0.0)

    # Final monetary amount allocated to this driver.
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0)

    status: Mapped[DividendShareStatus] = mapped_column(
        SAEnum(DividendShareStatus),
        default=DividendShareStatus.pending,
        nullable=False,
        index=True,
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    dividend = relationship("CooperativeDividend", back_populates="shares")
    driver = relationship("User", foreign_keys=[driver_id])
    driver_profile = relationship("DriverProfile", foreign_keys=[driver_profile_id])
