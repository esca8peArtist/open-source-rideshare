"""Corporate Invoice Dispute model.

Corporate account members can formally dispute charges on their invoices.
Employees submit disputes, account admins review them, and platform admins
resolve them.

Tables:
  corporate_invoice_disputes — one row per dispute; tracks status through
                               the full review lifecycle.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DisputeType(str, enum.Enum):
    """Category describing why the charge is being disputed."""

    incorrect_charge = "incorrect_charge"
    service_failure = "service_failure"
    duplicate_charge = "duplicate_charge"
    policy_violation = "policy_violation"
    unauthorized_ride = "unauthorized_ride"
    pricing_discrepancy = "pricing_discrepancy"
    other = "other"


class DisputeStatus(str, enum.Enum):
    """Lifecycle state of an invoice dispute."""

    submitted = "submitted"
    under_review = "under_review"
    resolved_upheld = "resolved_upheld"   # dispute upheld — credit/refund to account
    resolved_denied = "resolved_denied"   # dispute denied — original charge stands
    withdrawn = "withdrawn"               # member withdrew before resolution


class CorporateInvoiceDispute(Base):
    """A formal dispute raised against a corporate invoice.

    Members submit disputes for specific invoices.  Platform admins review and
    resolve them.  Each dispute has a structured type, a free-text description,
    and an optional list of specific ride IDs or disputed amount.

    Attributes:
        invoice_id: FK to corporate_invoices_v2.id (CASCADE delete).
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        submitted_by_id: FK to users — member who submitted the dispute.
            Nullable to allow system-initiated disputes.
        dispute_type: Structured DisputeType category.
        description: Required free-text explanation of the dispute.
        disputed_rides: Optional JSON list of ride IDs being disputed.
        disputed_amount_usd: Optional specific amount being disputed.
        status: Current lifecycle state of the dispute.
        resolution_note: Admin note explaining the resolution decision.
        resolved_by_id: FK to users — admin who resolved the dispute.
        resolved_at: Timestamp when the dispute was resolved.
        created_at: Row creation timestamp.
        updated_at: Row last-modification timestamp.
    """

    __tablename__ = "corporate_invoice_disputes"
    __table_args__ = (
        Index("ix_corp_inv_disputes_invoice_id", "invoice_id"),
        Index("ix_corp_inv_disputes_account_id", "account_id"),
        Index("ix_corp_inv_disputes_status", "status"),
        Index("ix_corp_inv_disputes_account_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_invoices_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    submitted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    dispute_type: Mapped[DisputeType] = mapped_column(
        Enum(DisputeType, name="disputetype"),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)

    disputed_rides: Mapped[list | None] = mapped_column(JSON, nullable=True)

    disputed_amount_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    status: Mapped[DisputeStatus] = mapped_column(
        Enum(DisputeStatus, name="disputestatus"),
        nullable=False,
        default=DisputeStatus.submitted,
    )

    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    resolved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    invoice = relationship("CorporateInvoice", foreign_keys=[invoice_id])
    submitted_by = relationship("User", foreign_keys=[submitted_by_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])
