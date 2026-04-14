"""Service layer for admin bulk notification broadcasts.

Provides:
  - get_broadcast_recipients  — resolve target audience from DB
  - send_bulk_notification    — create broadcast record and dispatch per-user
  - list_broadcasts           — paginated broadcast history
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.broadcast import BroadcastRecord
from app.models.user import User, UserRole
from app.schemas.bulk_notification import (
    BroadcastListItem,
    BroadcastTarget,
    BulkNotificationRequest,
    BulkNotificationResult,
)
from app.services.audit import log_event
from app.services.notifications import (
    Notification,
    NotificationChannel,
    NotificationType,
    send_notification,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_broadcast_recipients(
    db: AsyncSession,
    target: BroadcastTarget,
) -> list[User]:
    """Return active users matching the broadcast target filter.

    ALL     → every is_active user
    RIDERS  → is_active users with role RIDER
    DRIVERS → is_active users with role DRIVER
    """
    q = select(User).where(User.is_active == True)  # noqa: E712
    if target == BroadcastTarget.RIDERS:
        q = q.where(User.role == UserRole.RIDER)
    elif target == BroadcastTarget.DRIVERS:
        q = q.where(User.role == UserRole.DRIVER)
    result = await db.execute(q)
    return list(result.scalars().all())


async def send_bulk_notification(
    db: AsyncSession,
    admin_id: int,
    req: BulkNotificationRequest,
) -> BulkNotificationResult:
    """Dispatch a broadcast notification to all matching users.

    Steps:
    1. Resolve recipients.
    2. Persist a BroadcastRecord with recipient_count.
    3. For each user send one Notification; accumulate sent/failed counts.
    4. Update the record with final counts.
    5. Audit-log the action.
    6. Return a BulkNotificationResult.
    """
    recipients = await get_broadcast_recipients(db, req.target)
    recipient_count = len(recipients)

    # Map channel strings to NotificationChannel enum values, dropping unknowns.
    channel_map = {
        "push": NotificationChannel.PUSH,
        "sms": NotificationChannel.SMS,
        "email": NotificationChannel.EMAIL,
    }
    channels: list[NotificationChannel] = [
        channel_map[c] for c in req.channels if c in channel_map
    ]

    # Resolve notification type; fall back to PLATFORM_ANNOUNCEMENT.
    try:
        notif_type = NotificationType(req.notification_type)
    except ValueError:
        notif_type = NotificationType.PLATFORM_ANNOUNCEMENT

    # Persist initial BroadcastRecord.
    record = BroadcastRecord(
        admin_id=admin_id,
        target=req.target.value,
        title=req.title,
        body=req.body,
        channels=",".join(req.channels),
        recipient_count=recipient_count,
        sent_count=0,
        failed_count=0,
    )
    db.add(record)
    await db.flush()  # assigns record.id

    sent_count = 0
    failed_count = 0

    for user in recipients:
        notif = Notification(
            user_id=user.id,
            type=notif_type,
            title=req.title,
            body=req.body,
            channels=channels,
        )
        try:
            success = await send_notification(
                notif,
                db=db,
                phone=user.phone,
                email=user.email,
            )
            if success:
                sent_count += 1
            else:
                failed_count += 1
        except Exception:
            logger.exception(
                "Bulk notification failed for user %d in broadcast %d",
                user.id,
                record.id,
            )
            failed_count += 1

    # Update the record with final tallies.
    record.sent_count = sent_count
    record.failed_count = failed_count
    await db.flush()

    # Audit the broadcast action.
    try:
        await log_event(
            db,
            category="admin",
            event_type="bulk_notification_sent",
            description=(
                f"Admin {admin_id} broadcast '{req.title}' "
                f"to {req.target.value} ({recipient_count} recipients, "
                f"{sent_count} sent, {failed_count} failed)"
            ),
            actor_id=admin_id,
            actor_role="admin",
            metadata={
                "broadcast_id": record.id,
                "target": req.target.value,
                "channels": req.channels,
                "recipient_count": recipient_count,
                "sent_count": sent_count,
                "failed_count": failed_count,
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for broadcast %d", record.id)

    return BulkNotificationResult(
        broadcast_id=record.id,
        target=BroadcastTarget(record.target),
        title=record.title,
        recipient_count=record.recipient_count,
        sent_count=sent_count,
        failed_count=failed_count,
        created_at=record.created_at,
    )


async def list_broadcasts(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> list[BroadcastRecord]:
    """Return recent BroadcastRecords ordered newest-first."""
    q = (
        select(BroadcastRecord)
        .order_by(BroadcastRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())
