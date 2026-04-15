"""Corporate Account Contact model.

Enterprise accounts need to register non-billing operational contacts —
the people the platform can reach for account issues, travel policy questions,
employee onboarding, and legal/compliance matters.

CorporateAccountContact — one row per operational contact within a corporate
account.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ContactRole(str, enum.Enum):
    """Operational role of an account contact."""

    primary = "primary"
    travel_coordinator = "travel_coordinator"
    it_admin = "it_admin"
    hr = "hr"
    legal = "legal"
    other = "other"


class CorporateAccountContact(Base):
    """A designated operational contact for a corporate account.

    Operational contacts are the people the platform can reach for account
    issues, travel policy questions, employee onboarding, and legal/compliance
    matters.  Unlike billing contacts, these are categorised by role.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Display name of the contact (e.g. "Jane Smith").
        email: Contact email address, normalised to lowercase.  Unique per
            account — the same email address cannot appear twice on one account.
        phone: Optional phone number.
        title: Optional job title (e.g. "Head of Travel").
        contact_role: Operational role classification.
        notes: Optional free-form notes about this contact.
        is_primary: When True this is the single primary contact for the
            account.  At most one per account — enforced in the service layer.
        is_active: Soft-delete flag.  Inactive contacts are excluded from
            queries by default but preserved for history.
        added_by_id: FK to users — the admin who registered this contact.
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "corporate_account_contacts"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "email", name="uq_account_contact_email"
        ),
        Index("ix_corp_account_contacts_account_id", "account_id"),
        Index("ix_corp_account_contacts_role", "contact_role"),
        Index(
            "ix_corp_account_contacts_primary",
            "account_id",
            "is_primary",
            postgresql_where="is_primary = true",
        ),
        Index("ix_corp_account_contacts_active", "account_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)

    contact_role: Mapped[ContactRole] = mapped_column(
        Enum(ContactRole, name="contactrole"),
        nullable=False,
        default=ContactRole.other,
    )

    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

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
