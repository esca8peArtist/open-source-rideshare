"""Driver payout / disbursement model.

Tracks the full lifecycle of a payout to a driver for a given period:
  pending     — settlement calculated, waiting for admin review
  processing  — disbursement initiated
  completed   — funds delivered to driver
  failed      — disbursement failed; failed_reason explains why

Commission rate is resolved at payout-request time via the driver subscription
service.  Drivers on a flat-fee subscription pay 0 % commission; all others pay
the platform's standard 15 % commission.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DriverPayoutStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class DriverPayoutMethod(str, enum.Enum):
    stripe_transfer = "stripe_transfer"
    bank_transfer = "bank_transfer"
    manual = "manual"


class DriverPayout(Base):
    """Record of a disbursement to a driver for a given earning period."""

    __tablename__ = "driver_disbursements"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Monetary fields — stored with 2 d.p. precision.
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    platform_fee_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    net_payout_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    status: Mapped[DriverPayoutStatus] = mapped_column(
        SAEnum(DriverPayoutStatus), nullable=False, default=DriverPayoutStatus.pending
    )
    method: Mapped[DriverPayoutMethod] = mapped_column(
        SAEnum(DriverPayoutMethod), nullable=False, default=DriverPayoutMethod.stripe_transfer
    )

    # Earning period covered by this payout.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    driver = relationship("User", foreign_keys=[driver_id], backref="driver_disbursements")
