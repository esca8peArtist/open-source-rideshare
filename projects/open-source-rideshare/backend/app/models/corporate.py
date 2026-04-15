"""Corporate business account models.

Companies can create corporate accounts, add employee riders, set spending
limits, and receive consolidated billing via invoices.

BusinessAccount       — company-level billing account (table: corporate_accounts_v2)
BusinessAccountMember — employee membership with role-based access
BusinessInvoice       — periodic billing invoice per account

Note: Class names are prefixed "Business" to avoid collision with the
existing CorporateAccount/CorporateMembership models in corporate_account.py.
The public API and service layer expose them via the schema names "Corporate*".
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateAccountStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class MemberRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"


class BusinessAccount(Base):
    """A company-level billing account.

    Attributes:
        name: Display name of the organisation.
        tax_id: Optional company tax / VAT identifier.
        billing_email: Contact email for invoices.
        billing_address: Optional postal address for invoices.
        status: Lifecycle state of the account.
        monthly_budget_limit: Optional platform-wide monthly spend cap (NULL = unlimited).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        members: Related BusinessAccountMember rows.
        invoices: Related BusinessInvoice rows.
    """

    __tablename__ = "corporate_accounts_v2"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_email: Mapped[str] = mapped_column(String(254), nullable=False)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[CorporateAccountStatus] = mapped_column(
        SAEnum(CorporateAccountStatus),
        nullable=False,
        default=CorporateAccountStatus.PENDING,
    )

    monthly_budget_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
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

    members: Mapped[list["BusinessAccountMember"]] = relationship(
        "BusinessAccountMember",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list["BusinessInvoice"]] = relationship(
        "BusinessInvoice",
        back_populates="account",
        cascade="all, delete-orphan",
    )


class BusinessAccountMember(Base):
    """An employee's membership in a corporate account.

    Attributes:
        account_id: FK to corporate_accounts_v2.
        user_id: FK to users.
        role: 'admin' or 'member'.
        monthly_spend_limit: Optional per-member monthly cap (NULL = no cap).
        is_active: Whether the membership is currently active.
        joined_at: When the member was added.
    """

    __tablename__ = "corporate_account_members"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "user_id", name="uq_corp_member_account_user"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    role: Mapped[MemberRole] = mapped_column(
        SAEnum(MemberRole), nullable=False, default=MemberRole.MEMBER
    )
    monthly_spend_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped["BusinessAccount"] = relationship(
        "BusinessAccount", back_populates="members"
    )
    user = relationship("User", foreign_keys=[user_id])


class BusinessInvoice(Base):
    """A billing invoice for a corporate account covering a specific period.

    Attributes:
        account_id: FK to corporate_accounts_v2.
        billing_period_start: First day of the billing period.
        billing_period_end: Last day of the billing period.
        total_rides: Number of rides in the period.
        total_amount: Total amount billed.
        status: Invoice lifecycle state.
        issued_at: When the invoice was issued to the company.
        paid_at: When the invoice was marked as paid.
        created_at: Creation timestamp.
    """

    __tablename__ = "corporate_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id"), nullable=False, index=True
    )

    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)

    total_rides: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus), nullable=False, default=InvoiceStatus.DRAFT
    )

    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped["BusinessAccount"] = relationship(
        "BusinessAccount", back_populates="invoices"
    )
