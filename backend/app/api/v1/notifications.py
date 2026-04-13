from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.notification import NotificationLog, NotificationPreference
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationLogResponse,
    NotificationPreferenceResponse,
    UnreadNotificationCount,
    UpdateNotificationPreference,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---- Preferences ----


@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's notification preferences."""
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = NotificationPreference(user_id=user.id)
        db.add(prefs)
        await db.flush()
    return prefs


@router.put("/preferences", response_model=NotificationPreferenceResponse)
async def update_preferences(
    req: UpdateNotificationPreference,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's notification preferences."""
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = NotificationPreference(user_id=user.id)
        db.add(prefs)
        await db.flush()

    update_data = req.model_dump(exclude_unset=True)

    # Safety alerts cannot be fully disabled (SOS always goes through at service level)
    # but we allow the preference to be stored so the user sees their choice in the UI

    for field_name, value in update_data.items():
        setattr(prefs, field_name, value)

    await db.flush()
    return prefs


# ---- Notification History ----


@router.get("/history", response_model=NotificationListResponse)
async def get_notification_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    notification_type: str | None = Query(None),
    unread_only: bool = Query(False),
):
    """Get the current user's notification history."""
    query = select(NotificationLog).where(NotificationLog.user_id == user.id)

    if notification_type:
        query = query.where(NotificationLog.notification_type == notification_type)
    if unread_only:
        query = query.where(NotificationLog.is_read == False)  # noqa: E712

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Unread count
    unread_query = select(func.count()).where(
        NotificationLog.user_id == user.id,
        NotificationLog.is_read == False,  # noqa: E712
    )
    unread_count = (await db.execute(unread_query)).scalar() or 0

    # Fetch page
    query = query.order_by(NotificationLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    notifications = result.scalars().all()

    return NotificationListResponse(
        notifications=[NotificationLogResponse.model_validate(n) for n in notifications],
        total=total,
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=UnreadNotificationCount)
async def get_unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the count of unread notifications."""
    result = await db.execute(
        select(func.count()).where(
            NotificationLog.user_id == user.id,
            NotificationLog.is_read == False,  # noqa: E712
        )
    )
    count = result.scalar() or 0
    return UnreadNotificationCount(total_unread=count)


@router.post("/mark-read/{notification_id}")
async def mark_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single notification as read."""
    result = await db.execute(
        select(NotificationLog).where(
            NotificationLog.id == notification_id,
            NotificationLog.user_id == user.id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.is_read = True
    notif.read_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok"}


@router.post("/mark-all-read")
async def mark_all_notifications_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all of the current user's notifications as read."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(NotificationLog)
        .where(
            NotificationLog.user_id == user.id,
            NotificationLog.is_read == False,  # noqa: E712
        )
        .values(is_read=True, read_at=now)
    )
    await db.flush()
    return {"status": "ok"}
