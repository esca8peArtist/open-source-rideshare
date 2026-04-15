"""Corporate Ride Approval model.

Companies with strict expense control can require employees to obtain an
approval before booking a corporate ride.  Each approval carries a unique
code that is verified at booking time.

Lifecycle
---------
    pending   — submitted by employee, awaiting admin review
    approved  — admin approved; code is valid for booking until expires_at
    denied    — admin rejected the request
    expired   — approved but not used before expires_at
    cancelled — employee cancelled their own pending request
    used      — approval code was consumed at booking time

One approval per request; an employee may hold multiple approvals
concurrently (subject to account policy, enforced in the service layer).
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    USED = "used"


class CorporateRideApproval(Base):
    """A pre-booking ride approval request from an employee to their account admin."""

    __tablename__ = "corporate_ride_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Links
    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requester_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    # Request details (provided by employee)
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    destination_description: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Approval state
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus),
        nullable=False,
        default=ApprovalStatus.PENDING,
        index=True,
    )

    # Unique code used at booking time (UUID)
    approval_code: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    # Admin-set ceiling applied when approving (NULL = use estimated_cost_usd or uncapped)
    max_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Validity window
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Admin review
    review_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Usage tracking
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    requester = relationship("User", foreign_keys=[requester_user_id])
    reviewer = relationship("User", foreign_keys=[approved_by_user_id])
