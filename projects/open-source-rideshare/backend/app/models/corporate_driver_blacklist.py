"""Corporate Driver Blacklist model.

Enterprise accounts can block specific drivers from being dispatched on
their employees' corporate rides.  This is the inverse of the preferred
driver pool — where the pool surfaces trusted drivers first, the blacklist
permanently gates out drivers the account does not want.

CorporateDriverBlacklist — one row per (account_id, driver_id) pair.
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


class CorporateDriverBlacklist(Base):
    """A blacklisted driver entry for a corporate account.

    Admins add drivers by driver_profile id.  At matching time the routing
    layer can call is_driver_blacklisted() to exclude listed drivers from
    dispatch for corporate rides belonging to this account.

    Removing a driver soft-deletes the entry (is_active=False) so that the
    audit trail is preserved.  Re-adding a previously removed driver
    reactivates the existing row rather than creating a duplicate.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        driver_id: FK to driver_profiles (CASCADE delete).
        is_active: Soft-delete flag — False when the block is lifted.
        reason: Optional admin note explaining why the driver was blocked.
        blacklisted_by_id: FK to users — the admin who added this entry.
        blacklisted_at: UTC timestamp when the driver was blacklisted.
    """

    __tablename__ = "corporate_driver_blacklist"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "driver_id",
            name="uq_corp_driver_blacklist_account_driver",
        ),
        Index("ix_corp_driver_blacklist_account_id", "account_id"),
        Index("ix_corp_driver_blacklist_driver_id", "driver_id"),
        Index(
            "ix_corp_driver_blacklist_active",
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

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    blacklisted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    blacklisted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    blacklisted_by = relationship("User", foreign_keys=[blacklisted_by_id])
