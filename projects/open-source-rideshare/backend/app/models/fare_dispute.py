"""Fare dispute model — riders dispute a completed ride's fare.

Riders can submit a dispute against a completed ride if the fare was wrong,
the route was incorrect, the ride was incomplete, or an unauthorized charge
appeared. Admins review and decide: approve (full refund), partial (partial
refund), or deny.

Dispute lifecycle:
  PENDING → UNDER_REVIEW → APPROVED / PARTIAL / DENIED
  PENDING → WITHDRAWN (rider withdraws before admin review)
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DisputeCategory(str, enum.Enum):
    OVERCHARGE = "overcharge"
    INCORRECT_ROUTE = "incorrect_route"
    INCOMPLETE_RIDE = "incomplete_ride"
    UNAUTHORIZED_CHARGE = "unauthorized_charge"
    WAIT_TIME_FEE = "wait_time_fee"
    SURGE_PRICING = "surge_pricing"
    OTHER = "other"


class DisputeStatus(str, enum.Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    PARTIAL = "partial"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"


# Statuses that are terminal — no further transitions allowed
TERMINAL_STATUSES = {DisputeStatus.APPROVED, DisputeStatus.PARTIAL, DisputeStatus.DENIED, DisputeStatus.WITHDRAWN}

# Statuses that result in a refund
REFUND_STATUSES = {DisputeStatus.APPROVED, DisputeStatus.PARTIAL}


class FareDispute(Base):
    """A fare dispute filed by a rider against a completed ride.

    One active dispute is allowed per ride at a time — a rider can only have
    one non-withdrawn dispute open for any given ride.

    Columns
    -------
    ride_id           FK to rides.id — the disputed ride
    rider_id          FK to users.id — the rider who filed the dispute
    category          Reason category for the dispute
    description       Rider's explanation (required)
    disputed_amount   Amount the rider is disputing (≤ actual_fare)
    status            Workflow state (default PENDING)
    reviewed_by_admin_id  FK to users.id — admin who resolved it
    admin_notes       Internal notes from admin review
    refund_amount     Actual amount refunded (set on APPROVED/PARTIAL)
    stripe_refund_id  Stripe refund ID if processed
    resolved_at       Timestamp when status reached a terminal state
    """

    __tablename__ = "fare_disputes"

    id: Mapped[int] = mapped_column(primary_key=True)

    ride_id: Mapped[int] = mapped_column(
        ForeignKey("rides.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    category: Mapped[DisputeCategory] = mapped_column(
        SQLAlchemyEnum(DisputeCategory), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    disputed_amount: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[DisputeStatus] = mapped_column(
        SQLAlchemyEnum(DisputeStatus),
        default=DisputeStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Admin review
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    stripe_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    ride = relationship("Ride", foreign_keys=[ride_id])
    rider = relationship("User", foreign_keys=[rider_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_admin_id])
