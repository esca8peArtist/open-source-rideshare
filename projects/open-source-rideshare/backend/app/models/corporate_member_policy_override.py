"""Corporate Member Policy Override model.

Per-member exceptions to a corporate account's ride policy.  Admins can
grant individual members relaxed or tighter rules than the account-level
``CorporateRidePolicy``.  Common use-cases:

  - Executives allowed to book premium vehicles even when the account
    policy restricts to "standard".
  - Contractors capped at a lower per-ride cost than the account default.

Override fields are nullable: a ``NULL`` value means "inherit from the
account policy", so an override row only needs to specify the fields
being changed.

Only one override row is permitted per (account_id, member_id) pair
(enforced by a unique constraint).  Deactivation (is_active=False) keeps
history without removing the row.

Table:
  corporate_member_policy_overrides
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateMemberPolicyOverride(Base):
    """Per-member ride policy override within a corporate account.

    Attributes:
        account_id:                  FK to corporate_accounts_v2 (CASCADE).
        member_id:                   FK to corporate_account_members (CASCADE).
                                     The member this override applies to.
        overridden_by_id:            FK to users — admin who created/last
                                     updated this override (SET NULL on user
                                     deletion).
        allowed_vehicle_categories:  JSONB list of allowed vehicle types.
                                     NULL = inherit from account policy.
        max_per_ride_usd:            Per-ride cost cap for this member.
                                     NULL = inherit from account policy.
        require_purpose:             Whether the member must supply a trip
                                     purpose.  NULL = inherit.
        approved_purposes:           JSONB list of allowed purposes.
                                     NULL = inherit.
        business_hours_only:         Time-of-day restriction for this member.
                                     NULL = inherit.
        custom_notes:                Free-text annotation visible to admins
                                     only (max 500 chars).
        reason:                      Why the override was granted (max 300).
        is_active:                   Soft-delete flag.
        valid_from:                  When the override takes effect.
        valid_until:                 Expiry date; NULL = no expiry.
        created_at:                  Immutable creation timestamp.
        updated_at:                  Last-modified timestamp (auto-updated).

    Constraints:
        UniqueConstraint on (account_id, member_id) — one override row per
        member per account.
    """

    __tablename__ = "corporate_member_policy_overrides"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "member_id",
            name="uq_corp_member_policy_override",
        ),
        Index("ix_corp_member_policy_override_account_id", "account_id"),
        Index("ix_corp_member_policy_override_member_id", "member_id"),
        Index(
            "ix_corp_member_policy_override_account_active",
            "account_id",
            "is_active",
        ),
        Index("ix_corp_member_policy_override_valid_until", "valid_until"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    overridden_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Override fields — NULL means "inherit from account policy"
    allowed_vehicle_categories: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )
    max_per_ride_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    require_purpose: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_purposes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    business_hours_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    custom_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
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
    member = relationship("BusinessAccountMember", foreign_keys=[member_id])
    overridden_by = relationship("User", foreign_keys=[overridden_by_id])
