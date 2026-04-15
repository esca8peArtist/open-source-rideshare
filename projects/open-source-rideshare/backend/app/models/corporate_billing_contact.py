"""Corporate Billing Contact model.

Enterprise accounts need designated contacts who receive invoices and billing
notifications.  These contacts are often finance team members who are not
account admins and may not even be platform users — email-only contacts are
valid.

CorporateBillingContact — one row per billing contact within a corporate account.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateBillingContact(Base):
    """A designated billing contact for a corporate account.

    Billing contacts receive invoices and financial notifications on behalf of
    the enterprise account.  They may be finance team members who are not
    platform users (no ``users`` row required).

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Display name of the contact (e.g. "Jane Smith").
        email: Contact email address, normalised to lowercase.  Unique per
            account — the same email address cannot appear twice on one account.
        phone: Optional phone number.
        role: Optional free-text role label (e.g. "AP Manager", "CFO").
        receives_invoices: When True, this contact is included in invoice
            email dispatches.  Defaults to True.
        receives_budget_alerts: When True, this contact receives budget
            threshold alert emails.  Defaults to False.
        receives_monthly_summary: When True, this contact receives the
            monthly spend summary email.  Defaults to False.
        is_active: Soft-delete flag.  Inactive contacts are excluded from
            notification dispatch but preserved for history.
        added_by_id: FK to users — the admin who added this contact.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "corporate_billing_contacts"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "email", name="uq_billing_contact_account_email"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    receives_invoices: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    receives_budget_alerts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    receives_monthly_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    added_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
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
    added_by = relationship("User", foreign_keys=[added_by_id])
