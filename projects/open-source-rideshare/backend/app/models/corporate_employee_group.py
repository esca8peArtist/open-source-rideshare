"""Corporate Employee Group models.

Enterprise admins create named groups of employees that cross org-chart
boundaries — think "VIP Executives", "Remote Workers", "Engineering All-Hands".
Groups are more flexible than departments: one employee can belong to many
groups, and groups do not have to correspond to org structure.

CorporateEmployeeGroup — one named group per corporate account.
CorporateGroupMembership — many-to-many join between groups and account members.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class CorporateEmployeeGroup(Base):
    """A named employee group within a corporate account.

    Groups are flexible containers — one employee can belong to many groups and
    groups need not correspond to the org hierarchy.  Admins use them to apply
    policies, allocate budgets, or simply organise employees for reporting.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Display name, unique within the account (max 100 chars).
        description: Optional human-readable purpose of the group (max 500 chars).
        color: Optional hex colour for UI display, e.g. ``#FF5733`` (max 7 chars).
        is_active: Soft-delete flag.  False hides the group without removing history.
        created_by_id: FK to users — the admin who created this group (SET NULL on
            user delete so the group survives the admin's departure).
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_employee_groups"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "name", name="uq_corp_employee_group_account_name"
        ),
        Index("ix_corp_employee_group_account_id", "account_id"),
        Index(
            "ix_corp_employee_group_account_active",
            "account_id",
            "is_active",
            postgresql_where="is_active = true",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
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

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    memberships: Mapped[list["CorporateGroupMembership"]] = relationship(
        "CorporateGroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
    )


class CorporateGroupMembership(Base):
    """Membership of a BusinessAccountMember in a CorporateEmployeeGroup.

    A single member may belong to any number of groups simultaneously.  The
    combination of (group_id, member_id) is unique — the same member cannot
    be added to the same group twice.

    Attributes:
        group_id: FK to corporate_employee_groups (CASCADE delete).
        member_id: FK to corporate_account_members (CASCADE delete).
        added_by_id: FK to users — the admin who added this membership
            (SET NULL on user delete).
        created_at: UTC timestamp of when the membership was created.
    """

    __tablename__ = "corporate_group_memberships"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "member_id", name="uq_corp_group_membership_group_member"
        ),
        Index("ix_corp_group_membership_group_id", "group_id"),
        Index("ix_corp_group_membership_member_id", "member_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_employee_groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )

    added_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    group: Mapped["CorporateEmployeeGroup"] = relationship(
        "CorporateEmployeeGroup", back_populates="memberships"
    )
    member = relationship("BusinessAccountMember", foreign_keys=[member_id])
    added_by = relationship("User", foreign_keys=[added_by_id])
