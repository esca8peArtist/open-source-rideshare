"""Corporate Preferred Driver Pool model.

Enterprise accounts can designate a pool of preferred drivers — vetted,
trusted drivers the company wants routed for their employees' corporate rides.
The matching engine can surface pool drivers first when fulfilling a corporate
booking, giving companies continuity and quality assurance over their travel.

CorporateDriverPool — one row per (account_id, driver_id) pair.
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


class CorporateDriverPool(Base):
    """A preferred driver entry for a corporate account.

    Admins add drivers to the pool by driver_profile id.  At matching time
    the routing layer can query is_driver_preferred() to bias dispatch toward
    pool members.  Removing a driver performs a hard delete; history is
    preserved via the corporate admin audit log rather than a soft-delete flag
    (unlike most other corporate models the pool is operational, not a ledger).

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        driver_id: FK to driver_profiles.
        is_active: Soft-delete flag — False when admin removes a driver but
            wants to preserve the record (e.g. for audit).  Default True.
        notes: Optional admin notes about why this driver is preferred.
        added_by_id: FK to users — the admin who added this entry.
        added_at: UTC timestamp of when the driver was added to the pool.
    """

    __tablename__ = "corporate_driver_pool"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "driver_id", name="uq_corp_driver_pool_account_driver"
        ),
        Index("ix_corp_driver_pool_account_id", "account_id"),
        Index("ix_corp_driver_pool_driver_id", "driver_id"),
        Index(
            "ix_corp_driver_pool_active",
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

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    added_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    added_by = relationship("User", foreign_keys=[added_by_id])
