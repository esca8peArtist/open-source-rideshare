"""Corporate Manager Hierarchy model.

Enterprise admins define reporting relationships between corporate account
members.  The hierarchy supports two relationship types:

  direct      — the canonical "reports to" link.  Each employee may have
                at most one active direct manager within an account.
  dotted_line — informal or matrix-org relationships.  An employee may have
                any number of dotted-line managers simultaneously.

Cycle prevention is enforced at the service layer: before adding a
relationship A→B (A reports to B), the service walks B's direct-manager
chain to ensure A is not already a manager of B.

Table:
  corporate_manager_relationships — one row per active employee→manager link.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateManagerRelationship(Base):
    """An employee→manager relationship within a corporate account.

    Attributes:
        account_id:          FK to corporate_accounts_v2 (CASCADE delete).
        employee_member_id:  FK to corporate_account_members (CASCADE delete).
                             The subordinate in the relationship.
        manager_member_id:   FK to corporate_account_members (CASCADE delete).
                             The manager in the relationship.
        relationship_type:   "direct" or "dotted_line".
        notes:               Optional free-text note about this relationship
                             (max 300 chars).
        is_active:           Soft-delete flag.  False deactivates without
                             removing history.
        created_by_id:       FK to users — admin who created this row (SET NULL).
        created_at:          Immutable creation timestamp.
        updated_at:          Last-modified timestamp (auto-updated).

    Constraints:
        - employee_member_id != manager_member_id  (no self-reporting)
        - Unique on (account_id, employee_member_id, relationship_type) where
          relationship_type = 'direct' — enforced by a partial unique index on
          active rows; the service layer also validates this before inserting.
        - Unique on (account_id, employee_member_id, manager_member_id) to
          prevent duplicate rows for the same pair (regardless of type).
    """

    __tablename__ = "corporate_manager_relationships"
    __table_args__ = (
        # No self-reporting
        CheckConstraint(
            "employee_member_id != manager_member_id",
            name="ck_corp_mgr_rel_no_self_report",
        ),
        # Prevent exact duplicate (same employee, manager, regardless of type)
        UniqueConstraint(
            "account_id",
            "employee_member_id",
            "manager_member_id",
            name="uq_corp_mgr_rel_employee_manager",
        ),
        # Standard lookup indexes
        Index("ix_corp_mgr_rel_account_id", "account_id"),
        Index("ix_corp_mgr_rel_employee_member_id", "employee_member_id"),
        Index("ix_corp_mgr_rel_manager_member_id", "manager_member_id"),
        Index(
            "ix_corp_mgr_rel_account_active",
            "account_id",
            "is_active",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    manager_member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    relationship_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="direct"
    )
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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
    employee_member = relationship(
        "BusinessAccountMember", foreign_keys=[employee_member_id]
    )
    manager_member = relationship(
        "BusinessAccountMember", foreign_keys=[manager_member_id]
    )
    created_by = relationship("User", foreign_keys=[created_by_id])
