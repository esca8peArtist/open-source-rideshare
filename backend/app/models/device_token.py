"""DeviceToken model — stores FCM device tokens for push notifications."""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DevicePlatform(str, enum.Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class DeviceToken(Base):
    """FCM device token registered by a user for push notifications."""

    __tablename__ = "device_tokens"

    __table_args__ = (
        UniqueConstraint("token", name="uq_device_tokens_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    token: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    platform: Mapped[DevicePlatform] = mapped_column(Enum(DevicePlatform))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User", backref="device_tokens")
