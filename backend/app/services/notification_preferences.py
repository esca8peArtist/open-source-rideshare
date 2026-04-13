"""Service layer for per-user notification preferences.

Each preference row encodes a user's explicit opt-in/out for one
(notification_type, channel) combination.  The absence of a row means the
combination is *enabled* (opt-out model — safe default).

SOS_ALERT bypass
----------------
This service does NOT enforce the SOS_ALERT bypass itself.  That bypass is
documented here for clarity but is applied in ``send_notification()`` in
``app/services/notifications.py``.  ``is_channel_enabled()`` will faithfully
return whatever the user has stored; callers that need safety-critical
behaviour must check the notification type before consulting preferences.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.models.notification_preference import NotificationPreference

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# All valid notification types and channels — mirrored from the enums to avoid
# circular imports.
_ALL_NOTIFICATION_TYPES: list[str] = [
    "ride_matched",
    "ride_cancelled",
    "ride_completed",
    "driver_en_route",
    "driver_arrived",
    "payment_received",
    "sos_alert",
    "rating_received",
    "account_verification",
    "payout_completed",
    "ride_reminder",
    "fare_split_request",
    "promo_applied",
    "background_check_approved",
    "background_check_action_required",
]

_ALL_CHANNELS: list[str] = ["push", "sms", "email"]


async def get_user_preferences(
    db: AsyncSession,
    user_id: int,
) -> dict[str, dict[str, bool]]:
    """Return the full preference map for a user.

    Returns a nested dict of the form::

        {notification_type: {channel: enabled}}

    All type/channel combinations are present.  Combinations without a DB
    record default to True (enabled).
    """
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    rows = result.scalars().all()

    # Build a lookup keyed by (type, channel)
    stored: dict[tuple[str, str], bool] = {
        (row.notification_type, row.channel): row.enabled for row in rows
    }

    # Construct the full map, filling defaults
    preferences: dict[str, dict[str, bool]] = {}
    for notif_type in _ALL_NOTIFICATION_TYPES:
        preferences[notif_type] = {}
        for channel in _ALL_CHANNELS:
            preferences[notif_type][channel] = stored.get((notif_type, channel), True)

    return preferences


async def set_preference(
    db: AsyncSession,
    user_id: int,
    notification_type: str,
    channel: str,
    enabled: bool,
) -> NotificationPreference:
    """Set a single notification preference, upserting the DB record.

    Returns the saved NotificationPreference instance.
    """
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type == notification_type,
            NotificationPreference.channel == channel,
        )
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = NotificationPreference(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel,
            enabled=enabled,
        )
        db.add(pref)
    else:
        pref.enabled = enabled

    await db.flush()
    logger.debug(
        "Preference set: user=%d type=%s channel=%s enabled=%s",
        user_id,
        notification_type,
        channel,
        enabled,
    )
    return pref


async def bulk_set_preferences(
    db: AsyncSession,
    user_id: int,
    updates: list[dict],
) -> list[NotificationPreference]:
    """Set multiple preferences in one call.

    Each item in ``updates`` must contain keys: notification_type, channel, enabled.

    Returns the list of saved NotificationPreference instances in the same
    order as the input.
    """
    results: list[NotificationPreference] = []
    for update in updates:
        pref = await set_preference(
            db,
            user_id=user_id,
            notification_type=update["notification_type"],
            channel=update["channel"],
            enabled=update["enabled"],
        )
        results.append(pref)
    return results


async def is_channel_enabled(
    db: AsyncSession,
    user_id: int,
    notification_type: str,
    channel: str,
) -> bool:
    """Return whether a given channel is enabled for a user and notification type.

    Returns True when no preference record exists (opt-out model / safe default).

    SOS_ALERT note
    --------------
    This function does NOT apply the SOS_ALERT bypass.  The bypass is enforced
    by ``send_notification()`` in ``app/services/notifications.py`` before this
    function is called.  Callers that send safety-critical notifications must
    check for ``NotificationType.SOS_ALERT`` themselves.
    """
    result = await db.execute(
        select(NotificationPreference.enabled).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type == notification_type,
            NotificationPreference.channel == channel,
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        # No record — default is enabled
        return True

    return bool(row)


async def reset_preference(
    db: AsyncSession,
    user_id: int,
    notification_type: str,
    channel: str,
) -> bool:
    """Delete the preference record, resetting the combination to default (enabled).

    Returns True if a record was deleted, False if none existed.
    """
    result = await db.execute(
        delete(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type == notification_type,
            NotificationPreference.channel == channel,
        ).returning(NotificationPreference.id)
    )
    deleted_id = result.scalar_one_or_none()
    if deleted_id is not None:
        await db.flush()
        logger.debug(
            "Preference reset: user=%d type=%s channel=%s",
            user_id,
            notification_type,
            channel,
        )
        return True
    return False
