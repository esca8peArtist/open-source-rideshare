"""Driver subscription / flat-fee plan model.

Drivers can subscribe to a weekly or monthly flat-fee plan instead of paying
a per-ride commission.  While a subscription is active the platform charges
the flat fee and takes 0 % per-ride commission; without a subscription the
default commission is STANDARD_COMMISSION_PCT (15 %).

Plans:
  weekly  ($49 / week)  — flat fee, 0 % commission while active
  monthly ($149 / month) — flat fee, 0 % commission while active

Only one active subscription is allowed per driver at a time.  Cancellation
takes effect at the end of the current billing period (expires_at is not
changed; the driver keeps 0 % commission until then).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# Default per-ride commission rate when no active subscription exists.
STANDARD_COMMISSION_PCT: float = 15.0


class DriverSubscriptionPlan(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"


class DriverSubscriptionStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"   # cancelled but benefits valid until expires_at
    expired = "expired"


# Plan definitions: (price, billing_days, label)
PLAN_DETAILS: dict[DriverSubscriptionPlan, dict] = {
    DriverSubscriptionPlan.weekly: {
        "price": 49.00,
        "billing_days": 7,
        "label": "Weekly Plan",
    },
    DriverSubscriptionPlan.monthly: {
        "price": 149.00,
        "billing_days": 30,
        "label": "Monthly Plan",
    },
}


class DriverSubscription(Base):
    """A driver's flat-fee subscription record."""

    __tablename__ = "driver_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)

    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    plan: Mapped[DriverSubscriptionPlan] = mapped_column(
        SAEnum(DriverSubscriptionPlan), nullable=False
    )
    status: Mapped[DriverSubscriptionStatus] = mapped_column(
        SAEnum(DriverSubscriptionStatus),
        nullable=False,
        default=DriverSubscriptionStatus.active,
    )

    # Billing period
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Plan parameters snapshotted at subscription time so plan price changes
    # don't retroactively alter existing subscriptions.
    price: Mapped[float] = mapped_column(Float, nullable=False)
    commission_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Auto-renewal: if True the subscription renews at expires_at.
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)

    # External payment reference (populated when Stripe integration is active).
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Cancellation — set immediately when driver cancels, but expires_at is
    # NOT moved.  Driver retains 0 % commission until billing period ends.
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    driver = relationship("User", foreign_keys=[driver_id], backref="driver_subscriptions")
