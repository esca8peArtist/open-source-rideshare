"""Corporate / business account models.

Companies can create corporate accounts, invite employees (existing users),
and allow those employees to charge rides to the corporate account instead
of their personal payment method.

Lifecycle for a CorporateMembership
-------------------------------------
    pending    — invitation sent, employee has not yet accepted
    active     — employee accepted; may use corporate billing
    suspended  — temporarily blocked by admin (cannot use corporate billing)
    removed    — membership ended; employee no longer linked to the account
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class MembershipStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class CorporateAccount(Base):
    """A company-level billing account.

    Attributes:
        company_name: Display name for the organisation.
        billing_email: Contact email for invoices and billing queries.
        monthly_limit: Optional cap on the total company spend per calendar month.
            NULL means unlimited.
        per_ride_limit: Optional cap on a single ride under this account.
            NULL means unlimited.
        is_active: Inactive accounts cannot be used for new rides.
        current_month_spend: Running total for the current calendar month.
            Reset to 0.0 at the start of each new month by
            ``record_corporate_spend``.
        current_month: "YYYY-MM" string used to detect month rollovers.
        total_spend: Lifetime spend across all rides.
        created_at: Creation timestamp (server-set).
    """

    __tablename__ = "corporate_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)

    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    billing_email: Mapped[str] = mapped_column(String(200), nullable=False)

    monthly_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_ride_limit: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)

    current_month_spend: Mapped[float] = mapped_column(Float, default=0.0)
    current_month: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    memberships = relationship(
        "CorporateMembership",
        back_populates="account",
        cascade="all, delete-orphan",
    )


class CorporateMembership(Base):
    """An employee's membership in a corporate account.

    Attributes:
        account_id: The corporate account this membership belongs to.
        user_id: The platform user (employee) being invited/enrolled.
        monthly_limit: Optional per-employee monthly cap (NULL = no cap).
        status: Current lifecycle state.
        invited_at: When the invitation was created.
        activated_at: When the employee accepted the invite (NULL if pending/removed).
    """

    __tablename__ = "corporate_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    monthly_limit: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[MembershipStatus] = mapped_column(
        SAEnum(MembershipStatus),
        nullable=False,
        default=MembershipStatus.PENDING,
    )

    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    account = relationship("CorporateAccount", back_populates="memberships")
    user = relationship("User", foreign_keys=[user_id], backref="corporate_memberships")

    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_corporate_membership_account_user"),
    )
