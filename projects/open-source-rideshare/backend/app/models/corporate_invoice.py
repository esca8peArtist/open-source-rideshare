"""Corporate invoice model.

Companies receive monthly invoices summarising all completed rides billed to their
corporate account during a billing period.

CorporateInvoice — one row per invoice (draft → finalized → paid or void)
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    PAID = "paid"
    VOID = "void"


class CorporateInvoice(Base):
    """A monthly billing invoice for a corporate account.

    Attributes:
        account_id: FK to corporate_accounts_v2.
        invoice_number: Human-readable unique identifier, auto-generated at creation.
            Format: ``INV-{account_id:04d}-{YYYYMM}`` with a ``-N`` suffix if the
            base number is already taken for the period.
        period_start: Inclusive start date of the billing period.
        period_end: Inclusive end date of the billing period.
        status: Workflow state — draft → finalized → paid (or any → void).
        total_rides: Count of completed rides included in this invoice.
        subtotal_usd: Sum of actual_fare for all included rides.
        notes: Optional free-text note (visible to account admins).
        generated_at: When the invoice record was first created.
        finalized_at: When the invoice was moved to finalized status.
        paid_at: When the invoice was marked as paid.
        voided_at: When the invoice was voided.
        created_at: Row creation timestamp.
        updated_at: Row last-modification timestamp.
    """

    __tablename__ = "corporate_invoices_v2"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    invoice_number: Mapped[str] = mapped_column(
        String(30), nullable=False, unique=True
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus, name="corp_invoice_status_v2"),
        nullable=False,
        default=InvoiceStatus.DRAFT,
        index=True,
    )

    total_rides: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subtotal_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    account = relationship("BusinessAccount", foreign_keys=[account_id])
