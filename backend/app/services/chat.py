"""Chat service for in-ride messaging between driver and rider."""

import logging

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)

# Ride must be in one of these statuses for chat to be allowed
CHAT_ALLOWED_STATUSES = {
    RideStatus.MATCHED,
    RideStatus.DRIVER_EN_ROUTE,
    RideStatus.ARRIVED,
    RideStatus.IN_PROGRESS,
}


async def validate_chat_participant(
    db: AsyncSession, ride_id: int, user_id: int
) -> tuple[Ride | None, str | None]:
    """Validate that user_id is the rider or driver on an active ride.

    Returns (ride, error_message). If error_message is None, the ride is valid.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        return None, "Ride not found"

    if ride.status not in CHAT_ALLOWED_STATUSES:
        return None, f"Chat not available for ride in status: {ride.status.value}"

    if user_id not in (ride.rider_id, ride.driver_id):
        return None, "You are not a participant in this ride"

    return ride, None


def get_recipient_id(ride: Ride, sender_id: int) -> int:
    """Return the other participant's user ID."""
    return ride.driver_id if sender_id == ride.rider_id else ride.rider_id


async def save_message(
    db: AsyncSession,
    ride_id: int,
    sender_id: int,
    recipient_id: int,
    message: str,
) -> ChatMessage:
    """Persist a chat message to the database."""
    chat_msg = ChatMessage(
        ride_id=ride_id,
        sender_id=sender_id,
        recipient_id=recipient_id,
        message=message,
    )
    db.add(chat_msg)
    await db.commit()
    await db.refresh(chat_msg)
    return chat_msg


async def get_ride_messages(
    db: AsyncSession,
    ride_id: int,
    user_id: int,
    limit: int = 100,
    before_id: int | None = None,
) -> tuple[list[ChatMessage], int]:
    """Fetch chat messages for a ride (cursor-paginated).

    Only participants of the ride may fetch messages.
    Returns (messages, total_count).
    """
    ride, error = await validate_chat_participant(db, ride_id, user_id)
    if error:
        # For completed rides, allow reading history
        result = await db.execute(select(Ride).where(Ride.id == ride_id))
        ride = result.scalar_one_or_none()
        if not ride or user_id not in (ride.rider_id, ride.driver_id):
            return [], 0
        # Allow read access for completed/cancelled rides too

    # Total count
    count_q = select(func.count()).select_from(ChatMessage).where(
        ChatMessage.ride_id == ride_id
    )
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch messages
    q = (
        select(ChatMessage)
        .where(ChatMessage.ride_id == ride_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    if before_id:
        q = q.where(ChatMessage.id < before_id)

    result = await db.execute(q)
    messages = list(result.scalars().all())
    messages.reverse()  # chronological order
    return messages, total


async def mark_messages_read(
    db: AsyncSession, ride_id: int, reader_id: int
) -> int:
    """Mark all unread messages sent TO reader_id as read. Returns count updated."""
    stmt = (
        update(ChatMessage)
        .where(
            and_(
                ChatMessage.ride_id == ride_id,
                ChatMessage.recipient_id == reader_id,
                ChatMessage.is_read == False,  # noqa: E712
            )
        )
        .values(is_read=True)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount


async def get_unread_count(
    db: AsyncSession, ride_id: int, user_id: int
) -> int:
    """Count unread messages for user_id on a given ride."""
    q = select(func.count()).select_from(ChatMessage).where(
        and_(
            ChatMessage.ride_id == ride_id,
            ChatMessage.recipient_id == user_id,
            ChatMessage.is_read == False,  # noqa: E712
        )
    )
    return (await db.execute(q)).scalar() or 0
