"""REST endpoints for chat message history and read receipts."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.chat import ChatHistoryResponse, ChatMessageResponse, ChatMessageSend, UnreadCountResponse
from app.services.chat import (
    get_recipient_id,
    get_ride_messages,
    get_unread_count,
    mark_messages_read,
    save_message,
    validate_chat_participant,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/rides/{ride_id}/messages", response_model=ChatHistoryResponse)
async def get_chat_history(
    ride_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch chat messages for a ride. Only ride participants can access."""
    messages, total = await get_ride_messages(db, ride_id, user.id, limit, before_id)
    return ChatHistoryResponse(
        ride_id=ride_id,
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
        total=total,
    )


@router.post("/rides/{ride_id}/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_chat_message(
    ride_id: int,
    body: ChatMessageSend,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message via REST (alternative to WebSocket). Only active ride participants."""
    if body.ride_id != ride_id:
        raise HTTPException(status_code=400, detail="ride_id in body must match URL")

    ride, error = await validate_chat_participant(db, ride_id, user.id)
    if error:
        raise HTTPException(status_code=403, detail=error)

    recipient_id = get_recipient_id(ride, user.id)
    chat_msg = await save_message(db, ride_id, user.id, recipient_id, body.message)

    # Best-effort WebSocket relay
    from app.api.websocket import relay_chat_message
    await relay_chat_message(
        recipient_id=recipient_id,
        message_id=chat_msg.id,
        ride_id=ride_id,
        sender_id=user.id,
        message_text=body.message,
        created_at=chat_msg.created_at.isoformat(),
    )

    return ChatMessageResponse.model_validate(chat_msg)


@router.post("/rides/{ride_id}/messages/read")
async def mark_read(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all messages in a ride as read for the current user."""
    count = await mark_messages_read(db, ride_id, user.id)
    return {"ride_id": ride_id, "marked_read": count}


@router.get("/rides/{ride_id}/unread", response_model=UnreadCountResponse)
async def get_unread(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get count of unread messages for the current user on a ride."""
    count = await get_unread_count(db, ride_id, user.id)
    return UnreadCountResponse(ride_id=ride_id, unread_count=count)
