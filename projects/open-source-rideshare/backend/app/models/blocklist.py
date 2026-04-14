"""User blocklist model — riders and drivers block specific counterparties.

Either party (rider or driver) can block the other. Once a block is in place:
  - A rider who blocks a driver will never be matched with that driver.
  - A driver who blocks a rider will never receive ride offers from that rider.
  - The relationship is directional: blocker_id → blocked_id.
  - Both directions are checked during matching so either side can prevent contact.

A user can block at most MAX_BLOCKLIST_SIZE counterparties. This prevents abuse
of the system as a way to game matching.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

MAX_BLOCKLIST_SIZE = 50


class UserBlocklist(Base):
    """A unidirectional block between two users.

    Columns
    -------
    blocker_id    FK to users.id — user who created the block
    blocked_id    FK to users.id — user who is blocked
    reason        Optional free-text reason (internal, not shared with blocked user)
    created_at    When the block was created
    """

    __tablename__ = "user_blocklist"

    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocklist_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    blocker_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blocked_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    blocker = relationship("User", foreign_keys=[blocker_id])
    blocked = relationship("User", foreign_keys=[blocked_id])
