"""Corporate Guest Pass model.

Corporate employees can issue limited-use booking tokens (guest passes) to
non-employees such as clients, candidates, or visitors.  The guest presents
the token at booking time — no corporate login is required on their side.
The resulting ride is billed to the issuing corporate account.

CorporateGuestPass — table corporate_guest_passes
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class GuestPassStatus(str, enum.Enum):
    """Lifecycle states for a guest pass."""

    ACTIVE = "active"
    EXHAUSTED = "exhausted"   # max_uses reached
    EXPIRED = "expired"       # valid_until passed (informational; checked at validation time)
    REVOKED = "revoked"       # manually revoked by an admin/employee


class CorporateGuestPass(Base):
    """A limited-use booking token issued to a non-employee guest.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        created_by_employee_id: FK to users.id — the employee who issued the pass.
        token: Shareable UUID the guest submits when booking.  Unique globally.
        label: Human-readable description, e.g. "Client: ACME Interview".
        max_uses: Total allowed bookings, or NULL for unlimited.
        uses_remaining: Decrements on each booking; set to max_uses initially.
            NULL when max_uses is NULL (unlimited).
        max_ride_budget_usd: Optional per-ride spending cap in USD.
        trip_purpose_id: Optional FK to corporate_trip_purposes.id — auto-tags
            rides created with this pass.
        cost_center_id: Optional FK to corporate_cost_centers.id — charges rides
            to this cost center.
        valid_from: The earliest UTC datetime from which the token may be used.
        valid_until: The UTC datetime after which the token is no longer valid.
        status: Current lifecycle state.
        revoked_at: Timestamp when the pass was revoked, if applicable.
        revoked_by_id: FK to users.id — who revoked the pass.
        created_at: Row creation timestamp.
        updated_at: Row last-modification timestamp.
    """

    __tablename__ = "corporate_guest_passes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by_employee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        default=uuid.uuid4,
    )

    label: Mapped[str] = mapped_column(String(200), nullable=False)

    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)

    max_ride_budget_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id"),
        nullable=True,
        index=True,
    )
    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id"),
        nullable=True,
        index=True,
    )

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    status: Mapped[GuestPassStatus] = mapped_column(
        SAEnum(GuestPassStatus),
        nullable=False,
        default=GuestPassStatus.ACTIVE,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
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
    created_by_employee = relationship("User", foreign_keys=[created_by_employee_id])
    revoked_by = relationship("User", foreign_keys=[revoked_by_id])
