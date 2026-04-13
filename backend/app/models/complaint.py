"""Complaint model — formal complaint and dispute management between riders and drivers.

Riders or drivers can file formal complaints against each other regarding
specific trips. Admins review, investigate, and resolve or dismiss complaints.
This is a safety-critical feature that supports the platform's trust and safety goals.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ComplaintCategory(str, enum.Enum):
    UNSAFE_DRIVING = "unsafe_driving"
    HARASSMENT = "harassment"
    DISCRIMINATION = "discrimination"
    VEHICLE_CONDITION = "vehicle_condition"
    INAPPROPRIATE_BEHAVIOR = "inappropriate_behavior"
    FRAUD = "fraud"
    NO_SHOW = "no_show"
    WRONG_ROUTE = "wrong_route"
    OTHER = "other"


class ComplaintStatus(str, enum.Enum):
    PENDING = "pending"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Complaint(Base):
    """A formal complaint filed by one user against another, optionally tied to a ride.

    Either a rider or driver can file a complaint against the other party.
    Admins manage the lifecycle: PENDING -> REVIEWING -> RESOLVED or DISMISSED.

    admin_notes are only surfaced to the filing user once the complaint reaches
    a terminal status (resolved or dismissed) to prevent premature disclosure
    of investigation details.
    """

    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Who filed the complaint and who it is against
    filed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    against_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Optional ride reference — strongly encouraged but not required
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id"), nullable=True, index=True
    )

    # Complaint details
    category: Mapped[ComplaintCategory] = mapped_column(
        SQLAlchemyEnum(ComplaintCategory), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Workflow state
    status: Mapped[ComplaintStatus] = mapped_column(
        SQLAlchemyEnum(ComplaintStatus),
        default=ComplaintStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Admin resolution fields
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    filed_by = relationship("User", foreign_keys=[filed_by_user_id])
    against = relationship("User", foreign_keys=[against_user_id])
    ride = relationship("Ride", foreign_keys=[ride_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_admin_id])
