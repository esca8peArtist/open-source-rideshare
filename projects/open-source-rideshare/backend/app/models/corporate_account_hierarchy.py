"""Corporate Account Hierarchy model.

Enterprise accounts can define parent/child relationships with other corporate
accounts.  Use cases: a university managing department accounts, a corporation
with subsidiaries, or a franchise with location accounts.

Platform admins manage these relationships.  Account admins can view their own
hierarchy position.  The feature enables consolidated reporting across a tree.

Models:
  CorporateAccountHierarchy  — a directed parent→child link between two accounts

Table name:
  corporate_account_hierarchies
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class HierarchyRelationshipType(str, enum.Enum):
    """The nature of the relationship between a parent and child account."""

    subsidiary = "subsidiary"
    division = "division"
    franchise = "franchise"
    partner = "partner"


class CorporateAccountHierarchy(Base):
    """A directed parent→child link between two corporate accounts.

    Attributes:
        id: UUID primary key.
        parent_account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        child_account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        relationship_type: One of subsidiary, division, franchise, partner.
        notes: Optional free-text notes about this relationship.
        created_by_id: FK to users.id (SET NULL) — the admin who created this link.
        is_active: Soft-disable flag; inactive links are excluded from tree queries.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_account_hierarchies"
    __table_args__ = (
        UniqueConstraint(
            "parent_account_id",
            "child_account_id",
            name="uq_corp_hierarchy_parent_child",
        ),
        Index("ix_corp_hierarchy_parent_id", "parent_account_id"),
        Index("ix_corp_hierarchy_child_id", "child_account_id"),
        Index("ix_corp_hierarchy_parent_active", "parent_account_id", "is_active"),
        Index("ix_corp_hierarchy_child_active", "child_account_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    parent_account_id: Mapped[int] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    child_account_id: Mapped[int] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    relationship_type: Mapped[HierarchyRelationshipType] = mapped_column(
        Enum(HierarchyRelationshipType, name="hierarchyrelationshiptype"),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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

    parent_account = relationship(
        "BusinessAccount", foreign_keys=[parent_account_id], lazy="raise"
    )
    child_account = relationship(
        "BusinessAccount", foreign_keys=[child_account_id], lazy="raise"
    )
    created_by = relationship(
        "User", foreign_keys=[created_by_id], lazy="raise"
    )
