"""Corporate Credit Account and Transaction models.

Enterprise accounts can pre-load a balance that is drawn down per ride.
All credit movements are recorded in an append-only ledger table.

Tables:
  corporate_credit_accounts  — one row per corporate account; tracks current balance
                               and running totals.
  corporate_credit_transactions — append-only ledger; every deposit, deduction,
                                   refund, and manual adjustment.

The service layer keeps ``balance_usd`` and the running totals consistent by
updating them atomically with each transaction insert.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CreditTransactionType(str, enum.Enum):
    """Type of credit movement recorded in the ledger."""

    deposit = "deposit"         # Admin adds funds to the account
    deduction = "deduction"     # Ride charge drawn from the balance
    refund = "refund"           # Ride cancellation or dispute refund
    adjustment = "adjustment"   # Manual correction by platform admin (signed)


class CorporateCreditAccount(Base):
    """Per-account credit balance and cumulative totals.

    Attributes:
        id: Integer primary key.
        account_id: FK → corporate_accounts_v2 (unique — one row per account).
        balance_usd: Current available balance (never goes below 0 via service
            layer; adjustments that would produce a negative balance are rejected).
        total_deposited_usd: Cumulative deposits (deposits + positive adjustments).
        total_spent_usd: Cumulative deductions from rides.
        total_refunded_usd: Cumulative ride refunds credited back.
        low_balance_threshold_usd: Optional alert threshold; NULL means no alert.
        created_at / updated_at: Audit timestamps.
    """

    __tablename__ = "corporate_credit_accounts"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_corp_credit_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_deposited_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_spent_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_refunded_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    # Alert when balance falls below this threshold (NULL = disabled)
    low_balance_threshold_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
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
        backref="credit_account",
    )
    transactions: Mapped[list[CorporateCreditTransaction]] = relationship(
        "CorporateCreditTransaction",
        back_populates="credit_account",
        order_by="CorporateCreditTransaction.created_at.desc()",
    )


class CorporateCreditTransaction(Base):
    """Append-only ledger entry for a credit movement.

    Attributes:
        id: UUID primary key.
        account_id: FK → corporate_accounts_v2 (denormalized for efficient queries).
        credit_account_id: FK → corporate_credit_accounts.
        transaction_type: deposit / deduction / refund / adjustment.
        amount_usd: Absolute value of the movement (always positive).
        balance_after_usd: Snapshot of balance_usd immediately after this entry.
        reference_id: Optional external reference (ride ID, invoice ID, …).
        reference_type: Optional type tag ("ride", "invoice", …).
        description: Human-readable note.
        created_by_id: FK → users; NULL for system-generated deductions.
        created_at: Immutable creation timestamp.
    """

    __tablename__ = "corporate_credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credit_account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_credit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    transaction_type: Mapped[CreditTransactionType] = mapped_column(
        Enum(CreditTransactionType, name="credittransactiontype"),
        nullable=False,
        index=True,
    )

    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_after_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    reference_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    credit_account: Mapped[CorporateCreditAccount] = relationship(
        "CorporateCreditAccount", back_populates="transactions"
    )
    created_by = relationship("User", foreign_keys=[created_by_id])
