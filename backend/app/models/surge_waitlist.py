"""Surge waitlist entry model.

Riders can join a waitlist for a specific pickup location when surge pricing
is active. The system polls active entries and sends a notification when the
surge multiplier drops to or below the rider's specified threshold.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class WaitlistStatus(str):
    ACTIVE = "active"
    NOTIFIED = "notified"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SurgeWaitlistEntry(Base):
    __tablename__ = "surge_waitlist_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Pickup coordinates — required
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Optional destination
    destination_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    destination_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Notify when surge at origin drops to/below this threshold
    max_multiplier: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)

    # Optional vehicle service category filter (e.g. "standard", "xl")
    vehicle_preference: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Entry lifecycle status
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)

    # Notification channel preferences
    notify_via_push: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_via_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Expiry — entries auto-expire 2 hours after creation
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Set when a notification is dispatched
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
