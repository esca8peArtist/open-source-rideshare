"""Corporate Multi-Currency Billing models.

Corporate accounts operating internationally can bill in their local currency.
When ``auto_convert_invoices = True``, invoices get an FX rate snapshot recorded
at the time of invoicing.

Models:
  CorporateBillingCurrency
      — one record per corporate account, stores the preferred billing currency.
  CorporateInvoiceFXSnapshot
      — one record per invoice that uses a non-USD billing currency.

Tables:
  corporate_billing_currencies
  corporate_invoice_fx_snapshots
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateBillingCurrency(Base):
    """Billing currency configuration for a corporate account.

    One record per corporate account.  Created on first read via
    ``get_or_create_billing_currency``.  Defaults to USD.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), unique.
        billing_currency: ISO 4217 currency code (e.g. "USD", "EUR").
        auto_convert_invoices: When True, invoices get an FX rate snapshot.
        preferred_fx_provider: Audit label for the FX rate provider.
        is_active: Whether this config is active.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_billing_currencies"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_corp_billing_currency_account"),
        Index("ix_corp_billing_currency_account_id", "account_id"),
        Index("ix_corp_billing_currency_code", "billing_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    billing_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD"
    )

    auto_convert_invoices: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    preferred_fx_provider: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
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

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )


class CorporateInvoiceFXSnapshot(Base):
    """FX rate snapshot recorded at the time an invoice is issued.

    One record per invoice that uses a non-USD billing currency.
    USD-billed accounts do not get a snapshot (source == target).

    Attributes:
        id: UUID primary key.
        invoice_id: FK to corporate_invoices_v2 (CASCADE delete), unique.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        source_currency: Platform base currency — always "USD".
        target_currency: Account billing currency at the time of snapshot.
        exchange_rate: FX rate (source → target) at the time of snapshot.
        rate_captured_at: UTC datetime when the rate was recorded.
        rate_source: Human-readable label of where the rate came from.
        original_amount_usd: Invoice total in USD.
        converted_amount: Invoice total in the target currency.
        created_at: UTC timestamp when the snapshot was created.
    """

    __tablename__ = "corporate_invoice_fx_snapshots"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uq_corp_invoice_fx_snapshot"),
        Index("ix_corp_fx_snapshot_invoice_id", "invoice_id"),
        Index("ix_corp_fx_snapshot_account_id", "account_id"),
        Index("ix_corp_fx_snapshot_target_currency", "target_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_invoices_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD"
    )

    target_currency: Mapped[str] = mapped_column(
        String(3), nullable=False
    )

    exchange_rate: Mapped[sa.Numeric] = mapped_column(
        Numeric(16, 8), nullable=False
    )

    rate_captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    rate_source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    original_amount_usd: Mapped[sa.Numeric] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    converted_amount: Mapped[sa.Numeric] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
