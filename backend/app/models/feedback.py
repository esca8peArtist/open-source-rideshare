import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class FeedbackCategory(str, enum.Enum):
    SAFETY = "safety"
    CLEANLINESS = "cleanliness"
    NAVIGATION = "navigation"
    PROFESSIONALISM = "professionalism"
    VEHICLE_CONDITION = "vehicle_condition"
    COMMUNICATION = "communication"
    PRICING = "pricing"
    TIMELINESS = "timeliness"
    OTHER = "other"


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_RIDER_FAVOR = "resolved_rider_favor"
    RESOLVED_DRIVER_FAVOR = "resolved_driver_favor"
    RESOLVED_PARTIAL = "resolved_partial"
    DISMISSED = "dismissed"


class DisputeType(str, enum.Enum):
    FARE = "fare"
    ROUTE = "route"
    DRIVER_BEHAVIOR = "driver_behavior"
    RIDER_BEHAVIOR = "rider_behavior"
    SAFETY_CONCERN = "safety_concern"
    PROPERTY_DAMAGE = "property_damage"
    LOST_ITEM = "lost_item"
    CANCELLATION_FEE = "cancellation_fee"
    OTHER = "other"


class RideFeedback(Base):
    __tablename__ = "ride_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # "rider" or "driver"

    rating: Mapped[int]  # 1-5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    categories: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # comma-separated FeedbackCategory values

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ride = relationship("Ride", backref="feedback")
    user = relationship("User", backref="feedback_given")


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    filed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    dispute_type: Mapped[DisputeType] = mapped_column(Enum(DisputeType))
    status: Mapped[DisputeStatus] = mapped_column(
        Enum(DisputeStatus), default=DisputeStatus.OPEN
    )
    description: Mapped[str] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    refund_amount: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ride = relationship("Ride", backref="disputes")
    filer = relationship("User", foreign_keys=[filed_by], backref="disputes_filed")
    resolver = relationship(
        "User", foreign_keys=[resolved_by], backref="disputes_resolved"
    )
