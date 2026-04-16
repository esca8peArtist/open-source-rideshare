"""Corporate Auto-Approval Rule model.

Corporate account admins define rules that, when all specified conditions match
a ride request, automatically approve that ride without requiring a manual step
in the approval chain.  Multiple rules per account are allowed; if ANY rule
matches, auto-approval fires.  Rules are evaluated in descending priority order
(ties broken by created_at ASC).

Conditions are all optional — a null condition means "no constraint on this
dimension".  A rule matches only when every non-null condition is satisfied.

Tables:
  corporate_auto_approval_rules — one row per rule per corporate account.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateAutoApprovalRule(Base):
    """An auto-approval rule for a corporate account.

    When all non-null conditions on the rule are satisfied by a ride request
    the ride is considered auto-approved, bypassing the manual approval chain.

    Attributes:
        account_id:           FK to corporate_accounts_v2 (CASCADE delete).
        name:                 Human-readable rule name (unique within account
                              among active rules).
        is_active:            Soft toggle; inactive rules are never evaluated.
        max_cost_usd:         If set, ride estimated cost must be <= this value.
        trip_purpose_ids:     JSONB list of CorporateTripPurpose IDs; if set,
                              the ride's purpose must be in the list.
        cost_center_ids:      JSONB list of CorporateCostCenter IDs; if set,
                              the ride must be tagged to one of these centers.
        employee_group_ids:   JSONB list of CorporateEmployeeGroup IDs; if set,
                              the employee must belong to one of these groups.
        allowed_days_of_week: JSONB list of ints 0–6 (Mon=0); if set, the
                              ride's day of week must be in the list.
        start_hour:           If set (with end_hour), ride time >= start_hour.
        end_hour:             If set (with start_hour), ride time <= end_hour.
        priority:             Higher-priority rules are evaluated first; ties
                              broken by created_at ASC.
        created_by_id:        FK to users — admin who created the rule (SET NULL).
        created_at:           Immutable creation timestamp.
        updated_at:           Last-modified timestamp.
    """

    __tablename__ = "corporate_auto_approval_rules"
    __table_args__ = (
        Index("ix_corp_auto_approval_account_id", "account_id"),
        Index("ix_corp_auto_approval_is_active", "is_active"),
        Index(
            "ix_corp_auto_approval_account_active_priority",
            "account_id",
            "is_active",
            "priority",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    max_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    trip_purpose_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cost_center_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    employee_group_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    allowed_days_of_week: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
    created_by = relationship("User", foreign_keys=[created_by_id])
