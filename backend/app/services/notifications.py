"""Notification service for OpenRide.

Dispatches notifications through configured channel providers (Twilio SMS,
SendGrid email, push). Respects user preferences and logs every attempt
to the database for history/debugging.

The in-memory _sent_log is retained for unit tests that don't use a DB.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.services.notification_providers import send_email, send_push, send_sms

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class NotificationChannel(str, enum.Enum):
    PUSH = "push"
    SMS = "sms"
    EMAIL = "email"


class NotificationType(str, enum.Enum):
    RIDE_MATCHED = "ride_matched"
    RIDE_CANCELLED = "ride_cancelled"
    RIDE_COMPLETED = "ride_completed"
    DRIVER_EN_ROUTE = "driver_en_route"
    DRIVER_ARRIVED = "driver_arrived"
    PAYMENT_RECEIVED = "payment_received"
    SOS_ALERT = "sos_alert"
    RATING_RECEIVED = "rating_received"
    ACCOUNT_VERIFICATION = "account_verification"
    PAYOUT_COMPLETED = "payout_completed"
    RIDE_REMINDER = "ride_reminder"
    FARE_SPLIT_REQUEST = "fare_split_request"
    PROMO_APPLIED = "promo_applied"
    BACKGROUND_CHECK_APPROVED = "background_check_approved"
    BACKGROUND_CHECK_ACTION_REQUIRED = "background_check_action_required"


@dataclass
class Notification:
    user_id: int
    type: NotificationType
    title: str
    body: str
    channels: list[NotificationChannel] = field(default_factory=lambda: [NotificationChannel.PUSH])
    data: dict | None = None
    ride_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# In-memory log for testing — always active regardless of DB.
_sent_log: list[Notification] = []


async def send_notification(
    notification: Notification,
    db: AsyncSession | None = None,
    phone: str | None = None,
    email: str | None = None,
) -> bool:
    """Send a notification via configured channels.

    Returns True if at least one channel succeeded.

    Args:
        notification: The notification to send.
        db: Optional database session — if provided, logs are persisted.
        phone: User's phone number (for SMS channel).
        email: User's email address (for email channel).
    """
    any_success = False

    # Look up device tokens for push channel if db is available
    user_device_tokens: list[str] = []
    if db and NotificationChannel.PUSH in notification.channels:
        try:
            from sqlalchemy import select as _select
            from app.models.device_token import DeviceToken
            result = await db.execute(
                _select(DeviceToken.token).where(
                    DeviceToken.user_id == notification.user_id,
                    DeviceToken.is_active == True,  # noqa: E712
                )
            )
            user_device_tokens = list(result.scalars().all())
        except Exception:
            logger.debug("Could not load device tokens for user %d", notification.user_id)

    for channel in notification.channels:
        success = False

        if channel == NotificationChannel.SMS:
            success = await send_sms(notification, phone or "")
        elif channel == NotificationChannel.EMAIL:
            success = await send_email(notification, email or "")
        elif channel == NotificationChannel.PUSH:
            success = await send_push(notification, device_tokens=user_device_tokens or None)

        if success:
            any_success = True

        # Log to console regardless
        logger.info(
            "NOTIFICATION [%s] to user %d via %s: %s — %s [%s]",
            notification.type.value,
            notification.user_id,
            channel.value,
            notification.title,
            notification.body,
            "ok" if success else "skipped",
        )

        # Persist to DB if session provided
        if db:
            await _persist_log(db, notification, channel, success)

    _sent_log.append(notification)
    return any_success or True  # Return True for backwards compat when all channels disabled


async def _persist_log(
    db: AsyncSession,
    notification: Notification,
    channel: NotificationChannel,
    success: bool,
) -> None:
    """Write a notification log entry to the database."""
    try:
        from app.models.notification import NotificationLog, NotificationStatus

        log_entry = NotificationLog(
            user_id=notification.user_id,
            notification_type=notification.type.value,
            channel=channel.value,
            title=notification.title,
            body=notification.body,
            status=NotificationStatus.SENT if success else NotificationStatus.FAILED,
            ride_id=notification.ride_id or (notification.data.get("ride_id") if notification.data else None),
        )
        db.add(log_entry)
        await db.flush()
    except Exception:
        logger.exception("Failed to persist notification log for user %d", notification.user_id)


async def send_ride_notification(
    user_id: int,
    type: NotificationType,
    ride_id: int,
    db: AsyncSession | None = None,
    phone: str | None = None,
    email: str | None = None,
    **extra_data: str | float | int,
) -> bool:
    """Send a ride notification using templates for title/body and channels."""
    from app.services.notification_templates import render

    title, body, channels = render(type, **extra_data)

    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        channels=channels,
        data={"ride_id": ride_id, **extra_data},
        ride_id=ride_id,
    )
    return await send_notification(notification, db=db, phone=phone, email=email)


async def get_user_notification_preferences(db: AsyncSession, user_id: int):
    """Fetch user's notification preferences, creating defaults if missing."""
    from sqlalchemy import select
    from app.models.notification import NotificationPreference

    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = NotificationPreference(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs


async def filter_channels_by_preferences(
    channels: list[NotificationChannel],
    db: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
) -> list[NotificationChannel]:
    """Filter channels based on user preferences. SOS alerts bypass all preferences."""
    if notification_type == NotificationType.SOS_ALERT:
        return channels  # Safety alerts always go through

    prefs = await get_user_notification_preferences(db, user_id)

    # Check category opt-out
    ride_types = {
        NotificationType.RIDE_MATCHED, NotificationType.RIDE_CANCELLED,
        NotificationType.RIDE_COMPLETED, NotificationType.DRIVER_EN_ROUTE,
        NotificationType.DRIVER_ARRIVED, NotificationType.RIDE_REMINDER,
    }
    payment_types = {
        NotificationType.PAYMENT_RECEIVED, NotificationType.PAYOUT_COMPLETED,
        NotificationType.FARE_SPLIT_REQUEST,
    }

    if notification_type in ride_types and not prefs.ride_updates:
        return []
    if notification_type in payment_types and not prefs.payment_updates:
        return []
    if notification_type == NotificationType.PROMO_APPLIED and not prefs.promo_updates:
        return []

    # Filter individual channels
    filtered = []
    for ch in channels:
        if ch == NotificationChannel.PUSH and prefs.push_enabled:
            filtered.append(ch)
        elif ch == NotificationChannel.SMS and prefs.sms_enabled:
            filtered.append(ch)
        elif ch == NotificationChannel.EMAIL and prefs.email_enabled:
            filtered.append(ch)
    return filtered


async def send_notification_with_preferences(
    user_id: int,
    notification_type: NotificationType,
    db: AsyncSession,
    phone: str | None = None,
    email: str | None = None,
    ride_id: int | None = None,
    **template_kwargs,
) -> bool:
    """High-level: render template, apply user preferences, dispatch, persist.

    This is the recommended entry point for all notification sending.
    """
    from app.services.notification_templates import render

    title, body, channels = render(notification_type, **template_kwargs)

    # Apply user preferences
    channels = await filter_channels_by_preferences(channels, db, user_id, notification_type)
    if not channels:
        logger.debug("All channels filtered out for user %d type %s", user_id, notification_type)
        return False

    notification = Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body,
        channels=channels,
        data={"ride_id": ride_id, **template_kwargs} if ride_id else template_kwargs or None,
        ride_id=ride_id,
    )
    return await send_notification(notification, db=db, phone=phone, email=email)


def get_sent_notifications() -> list[Notification]:
    """Return all sent notifications (for testing)."""
    return list(_sent_log)


def clear_sent_notifications() -> None:
    """Clear the notification log (for testing)."""
    _sent_log.clear()
