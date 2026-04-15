"""Rider loyalty reward account and transaction models.

Riders earn points on every completed ride (based on fare paid) and can
redeem accumulated points for discounts on future rides.

Default rates (tunable via service constants):
  Earn rate  : POINTS_PER_DOLLAR = 10   — points earned per $1 of fare
  Point value: POINT_VALUE_CENTS  = 1   — each point is worth $0.01 on redemption
  Effective cashback rate: 10 × $0.01 / $1 = 10 %

Minimum redemption : MIN_REDEMPTION_POINTS = 500 (= $5 credit)
Max redemption     : MAX_REDEMPTION_PCT     = 50  — cannot cover >50 % of a single fare

Tables
------
rider_reward_accounts   — one row per rider; running balance + lifetime totals
rider_reward_transactions — audit log of every earn / redeem event
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Configurable constants
# ---------------------------------------------------------------------------

POINTS_PER_DOLLAR: int = 10          # points awarded per $1 of completed fare
POINT_VALUE_CENTS: int = 1            # 1 point = $0.01 when redeeming
MIN_REDEMPTION_POINTS: int = 500      # minimum redemption block (= $5)
MAX_REDEMPTION_PCT: float = 50.0      # points may cover at most 50 % of fare


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RewardTransactionType(str, enum.Enum):
    earn = "earn"               # points awarded after ride completion
    redeem = "redeem"           # points burned for a discount
    admin_adjust = "admin_adjust"  # manual admin credit / debit
    expiry = "expiry"           # future: points expired after inactivity


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RiderRewardAccount(Base):
    """One loyalty account per rider.  Created lazily on first earn or redeem."""

    __tablename__ = "rider_reward_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)

    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Current spendable balance (non-negative; cannot go below 0).
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Monotonically increasing totals for analytics.
    lifetime_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    rider = relationship("User", foreign_keys=[rider_id], backref="reward_account")
    transactions = relationship(
        "RiderRewardTransaction",
        back_populates="account",
        order_by="RiderRewardTransaction.created_at.desc()",
    )


class RiderRewardTransaction(Base):
    """Immutable audit log entry for every points change on a rider account."""

    __tablename__ = "rider_reward_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)

    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised FK to reward account for fast joins.
    account_id: Mapped[int] = mapped_column(
        ForeignKey("rider_reward_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable — admin adjustments and expiry events have no associated ride.
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    transaction_type: Mapped[RewardTransactionType] = mapped_column(
        SAEnum(RewardTransactionType), nullable=False
    )

    # Positive for earn/admin_credit, negative for redeem/expiry.
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    # Account balance immediately after this transaction was applied.
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    account = relationship("RiderRewardAccount", back_populates="transactions")
