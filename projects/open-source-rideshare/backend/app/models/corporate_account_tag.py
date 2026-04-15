"""Corporate Account Tag model.

Platform admins label corporate accounts with short, slugified tags
(e.g. ``vip``, ``at-risk``, ``healthcare``, ``government``) for internal
classification and cross-account filtering.

Tags are ad-hoc strings — there is no separate tag registry.  Tags are
normalised to lowercase, alphanumeric characters and hyphens, max 50 chars.

Tables:
  corporate_account_tags — one row per (account, tag) pair; unique constraint
                           prevents duplicate tags on the same account.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class CorporateAccountTag(Base):
    """A short label applied to a corporate account by a platform admin.

    Attributes:
        account_id:     FK to corporate_accounts_v2 (CASCADE delete).
        tag:            Normalised tag string (lowercase, a-z0-9 and hyphens,
                        max 50 chars).
        created_by_id:  FK to users (SET NULL when creator is deleted).
        created_at:     Immutable creation timestamp.
    """

    __tablename__ = "corporate_account_tags"
    __table_args__ = (
        UniqueConstraint("account_id", "tag", name="uq_corp_tag_account_tag"),
        Index("ix_corp_tag_account_id", "account_id"),
        Index("ix_corp_tag_tag", "tag"),
        Index("ix_corp_tag_created_by_id", "created_by_id"),
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

    tag: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
