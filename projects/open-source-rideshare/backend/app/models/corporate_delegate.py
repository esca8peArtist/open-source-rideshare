"""Corporate Delegate Access model.

Enterprise assistants (executive assistants, office managers) need to book rides
on behalf of other employees (executives, VIPs).  Corporate admins grant delegate
access with configurable permissions and optional spend caps.

Model
-----
CorporateDelegate  — a delegation granting one user (delegate) the ability to
                     book rides for another user (principal).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateDelegate(Base):
    """Grants a delegate user the ability to book rides for a principal user.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        principal_id: FK to users — the person being booked for.
        delegate_id: FK to users — the person doing the booking.
        can_book_rides: When True, the delegate may book rides on behalf of the principal.
        can_view_history: When True, the delegate may view the principal's corporate ride history.
        max_per_ride_usd: Optional per-ride spend cap.  Delegate bookings over this amount
            are denied by check_delegate_permission.  Null means no cap.
        valid_until: Optional expiry datetime.  After this instant the delegation is
            treated as expired by check_delegate_permission even if is_active is True.
        is_active: Soft-delete flag.  Revoked delegations are set to False.
        created_by_id: FK to users — the admin (or principal) who granted the delegation.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "corporate_delegates"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "principal_id", "delegate_id", name="uq_corp_delegate"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    principal_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )

    delegate_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )

    can_book_rides: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_view_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    max_per_ride_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
    principal = relationship("User", foreign_keys=[principal_id])
    delegate = relationship("User", foreign_keys=[delegate_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
