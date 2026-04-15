"""Corporate Ride Policy model.

Companies can define a ride policy that governs what kinds of rides their
employees may charge to the corporate account.  The policy is optional —
no policy means all rides are permitted.

One policy per corporate account (unique on account_id).

Columns
-------
account_id              FK → corporate_accounts_v2.id (unique — one row per account)
allowed_vehicle_categories  JSON array of allowed vehicle types; NULL = all allowed
                            e.g. ["standard", "xl"]
max_per_ride_usd        Maximum cost per ride under this account; NULL = unlimited
max_per_member_monthly_usd  Per-employee monthly spending cap; NULL = no individual cap
require_purpose         If True, employees must supply a trip purpose when booking
approved_purposes       JSON array of strings; NULL = any purpose accepted
                        Only enforced when require_purpose=True
business_hours_only     If True, restrict rides to Mon–Fri 07:00–21:00 (account's TZ)
                        Server evaluates in UTC when no timezone info is available
created_at / updated_at
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from decimal import Decimal

from app.db.database import Base


class CorporateRidePolicy(Base):
    """Per-account ride policy surfaced to the booking and dispatch engine."""

    __tablename__ = "corporate_ride_policies"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_corp_ride_policy_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Permitted vehicle types (NULL → all types allowed)
    allowed_vehicle_categories: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Per-ride cost cap (NULL → unlimited)
    max_per_ride_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Per-employee monthly cap (NULL → no individual cap beyond account-level budget)
    max_per_member_monthly_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Trip purpose requirements
    require_purpose: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    approved_purposes: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Time-of-day restriction
    business_hours_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account = relationship(
        "BusinessAccount",
        foreign_keys=[account_id],
        backref="ride_policy",
    )
