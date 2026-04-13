import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PayoutStatus(str, enum.Enum):
    PENDING = "pending"          # settlement calculated, not yet transferred
    PROCESSING = "processing"    # Stripe transfer initiated
    COMPLETED = "completed"      # funds delivered to driver's bank
    FAILED = "failed"            # transfer failed — needs retry or manual resolution


class PayoutFrequency(str, enum.Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    DAILY = "daily"


class DriverBankAccount(Base):
    """Stripe Connect account linked to a driver for receiving payouts."""

    __tablename__ = "driver_bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    stripe_connect_account_id: Mapped[str] = mapped_column(String(255))
    account_status: Mapped[str] = mapped_column(String(50), default="pending")
    bank_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payout_frequency: Mapped[PayoutFrequency] = mapped_column(
        Enum(PayoutFrequency), default=PayoutFrequency.WEEKLY,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    driver = relationship("User", backref="bank_account")


class DriverPayout(Base):
    """Record of a settlement payout to a driver for a given period."""

    __tablename__ = "driver_payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("driver_bank_accounts.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)

    ride_earnings: Mapped[float] = mapped_column(default=0.0)
    tip_earnings: Mapped[float] = mapped_column(default=0.0)
    cancellation_fee_earnings: Mapped[float] = mapped_column(default=0.0)
    bonus_amount: Mapped[float] = mapped_column(default=0.0)
    deductions: Mapped[float] = mapped_column(default=0.0)
    total_amount: Mapped[float] = mapped_column(default=0.0)

    trip_count: Mapped[int] = mapped_column(default=0)

    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[PayoutStatus] = mapped_column(Enum(PayoutStatus), default=PayoutStatus.PENDING)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    driver = relationship("User", backref="payouts")
    bank_account = relationship("DriverBankAccount", backref="payouts")
