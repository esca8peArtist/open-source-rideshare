"""Corporate Account Suspension model.

Platform admins can suspend corporate accounts for billing, compliance, or
policy reasons.  Reinstatement is equally explicit, and every suspension and
reinstatement event is kept for audit purposes.

Tables:
  corporate_account_suspensions — one row per suspension event; is_active=True
                                  means the account is currently suspended.
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
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class SuspensionReason(str, enum.Enum):
    """Reason a corporate account was suspended."""

    billing_overdue = "billing_overdue"
    policy_violation = "policy_violation"
    fraud_investigation = "fraud_investigation"
    voluntary_pause = "voluntary_pause"
    compliance_failure = "compliance_failure"
    non_payment = "non_payment"
    other = "other"


class CorporateAccountSuspension(Base):
    """Record of a single suspension event for a corporate account.

    One active suspension per account at a time (enforced in the service layer).
    Historical records are retained after reinstatement for audit purposes.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        suspended_by_id: FK to users — admin who triggered the suspension.
            Nullable to allow system-initiated suspensions.
        reason: Structured SuspensionReason category.
        suspension_note: Free-text admin note explaining the suspension.
        suspended_at: Timestamp when the suspension was created.
        reinstated_at: Timestamp when the account was reinstated; null if active.
        reinstated_by_id: FK to users — admin who reinstated the account.
        reinstatement_note: Free-text note recorded on reinstatement.
        is_active: True while the suspension is in effect; False once reinstated.
    """

    __tablename__ = "corporate_account_suspensions"
    __table_args__ = (
        Index("ix_corp_suspensions_account_id", "account_id"),
        Index("ix_corp_suspensions_is_active", "is_active"),
        Index("ix_corp_suspensions_account_is_active", "account_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    suspended_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[SuspensionReason] = mapped_column(
        Enum(SuspensionReason, name="suspensionreason"),
        nullable=False,
    )

    suspension_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    suspended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    reinstated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reinstated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reinstatement_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    suspended_by = relationship("User", foreign_keys=[suspended_by_id])
    reinstated_by = relationship("User", foreign_keys=[reinstated_by_id])
