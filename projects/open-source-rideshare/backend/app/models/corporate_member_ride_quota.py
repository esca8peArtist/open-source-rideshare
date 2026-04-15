"""Corporate Member Ride Quota model.

Corporate account admins can set per-member ride count limits scoped to a
time period (daily, weekly, monthly).  A quota row represents the maximum
number of corporate rides a specific employee may take in a given period.

When a quota is inactive (is_active=False) rides are unrestricted for that
member/period combination.  Inactive quotas are kept for auditing and may be
reactivated.

Tables:
  corporate_member_ride_quotas — one row per active (account, member, period)
                                  combination; unique constraint prevents
                                  duplicate active quotas for the same triple.
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


class CorporateMemberRideQuota(Base):
    """A per-member ride count limit applied by a corporate account admin.

    Attributes:
        account_id:     FK to corporate_accounts_v2 (CASCADE delete).
        member_id:      FK to users — the employee being quota-d (CASCADE delete).
        period:         Time window for the quota: "daily", "weekly", or "monthly".
        max_rides:      Maximum number of corporate rides allowed per period (>=1).
        is_active:      Whether this quota is currently enforced.
        created_by_id:  FK to users — admin who created the quota (SET NULL).
        created_at:     Immutable creation timestamp.
        updated_at:     Last-modified timestamp (auto-updated).
    """

    __tablename__ = "corporate_member_ride_quotas"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "member_id",
            "period",
            name="uq_corp_quota_account_member_period",
        ),
        Index("ix_corp_quota_account_id", "account_id"),
        Index("ix_corp_quota_member_id", "member_id"),
        Index("ix_corp_quota_account_period", "account_id", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    period: Mapped[str] = mapped_column(String(10), nullable=False)
    max_rides: Mapped[int] = mapped_column(Integer, nullable=False)
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
    member = relationship("User", foreign_keys=[member_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
