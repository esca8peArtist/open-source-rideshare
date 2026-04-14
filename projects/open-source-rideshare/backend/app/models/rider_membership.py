"""Rider membership / subscription plan model.

Riders can subscribe to a monthly membership plan for fare discounts and
surge price caps.  The platform currently offers two tiers:

  Basic   ($9.99/mo)  — 10 % fare discount, surge cap at 2.0×
  Premium ($19.99/mo) — 20 % fare discount, surge cap at 1.5×, priority match

Only one active membership is allowed per rider at a time.  Cancellation
takes effect at the end of the current billing period (expires_at is not
changed; the rider keeps their benefits until then).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class MembershipPlan(str, enum.Enum):
    basic = "basic"
    premium = "premium"


class MembershipStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"   # cancelled but benefits valid until expires_at
    expired = "expired"


class RiderMembership(Base):
    __tablename__ = "rider_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)

    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    plan: Mapped[MembershipPlan] = mapped_column(SAEnum(MembershipPlan), nullable=False)
    status: Mapped[MembershipStatus] = mapped_column(
        SAEnum(MembershipStatus),
        nullable=False,
        default=MembershipStatus.active,
    )

    # Billing period
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Plan parameters snapshotted at subscription time (so plan changes don't
    # retroactively alter existing subscriptions).
    monthly_price: Mapped[float] = mapped_column(Float, nullable=False)
    fare_discount_pct: Mapped[float] = mapped_column(Float, nullable=False)
    surge_cap_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    priority_matching: Mapped[bool] = mapped_column(default=False)

    # External payment reference (populated when Stripe integration is active).
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Cancellation — set immediately when rider cancels, but expires_at is NOT
    # moved.  The rider retains benefits until the billing period ends.
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rider = relationship("User", foreign_keys=[rider_id], backref="memberships")
