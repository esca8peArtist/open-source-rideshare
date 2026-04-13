"""NotificationPreference model — per-user, per-type, per-channel opt-in/out.

Each row encodes a user's explicit preference for one (notification_type, channel)
combination.  If no row exists for a given combination the system treats the
notification as *enabled* (opt-out model).

SOS_ALERT notifications are always dispatched regardless of preferences; that
bypass lives in the send_notification() service layer, not here.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class NotificationPreference(Base):
    """Per-user opt-in/out keyed by notification_type + channel.

    Columns
    -------
    user_id           FK to users.id
    notification_type String value from NotificationType enum (e.g. "ride_matched")
    channel           String value from NotificationChannel enum ("push", "sms", "email")
    enabled           False = user has opted out of this type/channel combination
    """

    __tablename__ = "notification_preferences_v2"

    __table_args__ = (
        UniqueConstraint(
            "user_id", "notification_type", "channel",
            name="uq_notif_pref_user_type_channel",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User", backref="notification_preferences_v2")
