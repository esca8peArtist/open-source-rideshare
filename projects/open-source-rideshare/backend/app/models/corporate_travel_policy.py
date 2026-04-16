"""Corporate Travel Policy & Acknowledgement models.

Corporate accounts publish a versioned travel policy document that employees
must formally acknowledge before booking corporate rides.  Admins create and
version the policy; one policy at a time may be active.  Acknowledgements are
append-only compliance records.

Models:
  CorporateTravelPolicy
      — versioned policy document (one active per account at a time)
  CorporatePolicyAcknowledgement
      — append-only record of an employee acknowledging the active policy

Table names:
  corporate_travel_policies
  corporate_policy_acknowledgements
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateTravelPolicy(Base):
    """A versioned corporate travel policy document.

    Only one policy may be ``is_active=True`` per account at any time.
    Activating a new policy automatically deactivates the previous one.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        title: Short human-readable title (e.g. "Q2 2026 Travel Policy").
        content: Full policy text (plain text or Markdown).
        version_number: Monotonically increasing version label (e.g. "1",
            "2.1").  Free-form string — admins control the numbering scheme.
        is_active: Only one active policy allowed per account at a time.
        requires_acknowledgement: When True, employees must acknowledge
            this policy before booking corporate rides.
        effective_date: Optional date from which the policy applies.
        created_by_id: FK to users (SET NULL) — admin who created it.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_travel_policies"
    __table_args__ = (
        Index("ix_corp_travel_policy_account_id", "account_id"),
        Index("ix_corp_travel_policy_is_active", "is_active"),
        Index("ix_corp_travel_policy_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    version_number: Mapped[str] = mapped_column(String(50), nullable=False, default="1")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    requires_acknowledgement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    effective_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    acknowledgements = relationship(
        "CorporatePolicyAcknowledgement",
        back_populates="policy",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporatePolicyAcknowledgement(Base):
    """Append-only record of an employee acknowledging a corporate travel policy.

    One acknowledgement row per (policy, member) pair — employees can only
    acknowledge a policy once.  Records are immutable once created.

    Attributes:
        id: Integer primary key.
        policy_id: FK to corporate_travel_policies (CASCADE delete).
        member_id: FK to users (SET NULL on user deletion — preserve audit
            history even if employee account is removed).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete)
            for efficient per-account queries.
        acknowledged_at: UTC timestamp of the acknowledgement.
    """

    __tablename__ = "corporate_policy_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "member_id",
            name="uq_corp_policy_ack_policy_member",
        ),
        Index("ix_corp_policy_ack_policy_id", "policy_id"),
        Index("ix_corp_policy_ack_member_id", "member_id"),
        Index("ix_corp_policy_ack_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    policy_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_travel_policies.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    policy = relationship(
        "CorporateTravelPolicy",
        foreign_keys=[policy_id],
        back_populates="acknowledgements",
        lazy="raise",
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
