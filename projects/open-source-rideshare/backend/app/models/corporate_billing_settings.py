"""Corporate Billing Settings models.

Corporate accounts configure how they want to be billed: billing address,
tax/EIN number, PO number requirements, auto-pay preference, billing cycle,
and invoice email recipients.  Payment methods (cards, ACH, wire) are stored
as separate rows so an account can have multiple methods with one designated
as default.

CorporateBillingSettings — one per corporate account (upsert semantics).
CorporatePaymentMethod   — one or more payment methods per account.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class BillingCycle(str, enum.Enum):
    """Frequency at which the platform generates invoices for this account."""

    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"


class PaymentMethodType(str, enum.Enum):
    """Type of payment instrument stored on the account."""

    credit_card = "credit_card"
    debit_card = "debit_card"
    ach_bank_account = "ach_bank_account"
    wire_transfer = "wire_transfer"


class CorporateBillingSettings(Base):
    """Billing configuration for a corporate account.

    One row per account (unique constraint on ``account_id``).  Settings are
    created lazily via upsert when an admin saves billing configuration for the
    first time.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        billing_company_name: Legal entity name for invoices.  If null, the
            account's own name is used by the invoice generator.
        billing_address_line1: Street address line 1.
        billing_address_line2: Optional street address line 2 (suite, floor, etc.).
        billing_city: City.
        billing_state: State / province / region.
        billing_postal_code: ZIP / postal code.
        billing_country: ISO 3166-1 alpha-2 country code, e.g. "US".
        tax_id: Tax identification number (EIN, VAT ID, etc.) shown on invoices.
        po_number_required: When True, invoices must include a PO number.
        default_po_number: Standing PO number pre-filled on all new invoices.
        invoice_memo_template: Optional boilerplate text appended to every invoice.
        auto_pay_enabled: When True, outstanding invoices are charged automatically
            to the default payment method when they are finalised.
        billing_cycle: How frequently invoices are generated (weekly/biweekly/monthly).
        invoice_emails: JSONB list of email addresses that receive invoice PDFs.
        updated_by_id: FK to users — last admin to save settings.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_billing_settings"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            name="uq_corp_billing_settings_account_id",
        ),
        Index("ix_corp_billing_settings_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    billing_company_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    billing_address_line1: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    billing_address_line2: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    billing_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    billing_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    billing_postal_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )

    billing_country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    po_number_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    default_po_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    invoice_memo_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    auto_pay_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    billing_cycle: Mapped[BillingCycle] = mapped_column(
        Enum(BillingCycle, name="billingcycle"),
        nullable=False,
        default=BillingCycle.monthly,
    )

    invoice_emails: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    payment_methods: Mapped[list["CorporatePaymentMethod"]] = relationship(
        "CorporatePaymentMethod",
        back_populates="billing_settings",
        cascade="all, delete-orphan",
    )


class CorporatePaymentMethod(Base):
    """A payment instrument registered on a corporate billing account.

    Accounts may hold multiple payment methods.  Exactly one may be flagged
    ``is_default=True``; the service layer enforces this invariant.  This model
    stores display-safe metadata only — raw card numbers are never persisted.
    The ``external_payment_method_id`` field is intended to hold the Stripe
    PaymentMethod ID (``pm_…``) or equivalent gateway reference.

    Attributes:
        billing_settings_id: FK to corporate_billing_settings (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 for direct queries
            without a join to billing_settings.
        payment_type: PaymentMethodType enum.
        display_name: Human-readable label, e.g. "Corporate Visa ending 4242".
        last_four: Last four digits of card number or bank account number.
        cardholder_name: Name on the card or bank account.
        bank_name: Bank name (for ACH / wire methods).
        external_payment_method_id: Gateway reference (e.g. Stripe ``pm_…``).
        is_default: True if this is the account's primary payment method.
        is_active: Soft-delete flag.
        created_by_id: FK to users — admin who added this method.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_payment_methods"
    __table_args__ = (
        Index("ix_corp_payment_methods_billing_settings_id", "billing_settings_id"),
        Index("ix_corp_payment_methods_account_id", "account_id"),
        Index("ix_corp_payment_methods_is_default", "account_id", "is_default"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    billing_settings_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_billing_settings.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    payment_type: Mapped[PaymentMethodType] = mapped_column(
        Enum(PaymentMethodType, name="paymentmethodtype"),
        nullable=False,
    )

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)

    cardholder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    external_payment_method_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    billing_settings: Mapped["CorporateBillingSettings"] = relationship(
        "CorporateBillingSettings", back_populates="payment_methods"
    )
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
