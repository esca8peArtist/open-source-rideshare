import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationLog(Base):
    """Persistent record of every notification sent (or attempted)."""

    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(50), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # push, sms, email
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus), default=NotificationStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ride_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="notification_logs")


class NotificationPreference(Base):
    """Per-user opt-in/out for notification channels and types."""

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # hour 0-23
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ride_updates: Mapped[bool] = mapped_column(Boolean, default=True)
    payment_updates: Mapped[bool] = mapped_column(Boolean, default=True)
    promo_updates: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_alerts: Mapped[bool] = mapped_column(Boolean, default=True)  # SOS — always on by default
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    user = relationship("User", backref="notification_preferences")
