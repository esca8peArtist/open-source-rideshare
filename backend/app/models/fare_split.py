import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class SplitStatus(str, enum.Enum):
    PENDING = "pending"      # Invite sent, awaiting response
    ACCEPTED = "accepted"    # Invitee accepted their share
    DECLINED = "declined"    # Invitee declined
    PAID = "paid"            # Invitee's share has been paid
    EXPIRED = "expired"      # Invite expired (ride completed without response)
    CANCELLED = "cancelled"  # Initiator cancelled the split


class FareSplit(Base):
    """Tracks fare splitting for a ride.

    The ride initiator can split the fare with 1-4 other users.
    Each FareSplit row represents one participant's share.
    The initiator also gets a row (is_initiator=True).
    """
    __tablename__ = "fare_splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)

    # The user who owns this share (null if invited by phone/email and not yet registered)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    # For inviting non-registered users
    invite_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    invite_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_initiator: Mapped[bool] = mapped_column(default=False)
    status: Mapped[SplitStatus] = mapped_column(Enum(SplitStatus), default=SplitStatus.PENDING)

    # Share details — set when split is created, updated if participants change
    share_amount: Mapped[float] = mapped_column(default=0.0)
    share_percentage: Mapped[float] = mapped_column(default=0.0)  # 0.0 to 100.0

    # Payment tracking
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ride = relationship("Ride", backref="fare_splits")
    user = relationship("User", backref="fare_split_shares")
