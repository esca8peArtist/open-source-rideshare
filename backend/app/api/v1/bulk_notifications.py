"""Admin bulk notification broadcast API.

All endpoints require admin authentication.

Endpoints:
  POST /admin/notifications/broadcast        — send a broadcast to target users
  GET  /admin/notifications/broadcasts       — list past broadcasts (paginated)
  GET  /admin/notifications/broadcasts/{id}  — detail for a single broadcast
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.broadcast import BroadcastRecord
from app.models.user import User
from app.schemas.bulk_notification import (
    BroadcastListItem,
    BroadcastTarget,
    BulkNotificationRequest,
    BulkNotificationResult,
)
from app.services.bulk_notifications import (
    list_broadcasts,
    send_bulk_notification,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/notifications",
    tags=["admin", "notifications"],
)

_VALID_CHANNELS = {"push", "sms", "email"}


@router.post(
    "/broadcast",
    response_model=BulkNotificationResult,
    status_code=201,
    summary="Send a bulk notification broadcast",
    description=(
        "Dispatch a notification to all active users matching the chosen target "
        "(all, riders, or drivers). Channels must be a non-empty subset of "
        "['push', 'sms', 'email']. Requires admin authentication."
    ),
)
async def broadcast(
    req: BulkNotificationRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkNotificationResult:
    """Send a broadcast notification to the target audience."""
    # Validate channels (Pydantic already does this via field_validator,
    # but we repeat the check here for belt-and-suspenders safety).
    invalid = set(req.channels) - _VALID_CHANNELS
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid channel(s): {sorted(invalid)}. "
                f"Must be a subset of: {sorted(_VALID_CHANNELS)}"
            ),
        )
    if not req.channels:
        raise HTTPException(
            status_code=422,
            detail="At least one channel is required",
        )

    return await send_bulk_notification(db, admin_id=current_user.id, req=req)


@router.get(
    "/broadcasts",
    response_model=list[BroadcastListItem],
    summary="List past broadcast records",
    description=(
        "Returns a paginated list of past admin broadcasts ordered newest-first. "
        "Requires admin authentication."
    ),
)
async def broadcasts_list(
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[BroadcastListItem]:
    """Paginated list of broadcast records, newest first."""
    records = await list_broadcasts(db, limit=limit, offset=offset)
    return [
        BroadcastListItem(
            broadcast_id=r.id,
            target=BroadcastTarget(r.target),
            title=r.title,
            recipient_count=r.recipient_count,
            sent_count=r.sent_count,
            failed_count=r.failed_count,
            admin_id=r.admin_id,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.get(
    "/broadcasts/{broadcast_id}",
    response_model=BulkNotificationResult,
    summary="Get a single broadcast record",
    description=(
        "Returns full detail for one broadcast record by ID. "
        "Returns 404 if the broadcast does not exist. "
        "Requires admin authentication."
    ),
)
async def broadcast_detail(
    broadcast_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkNotificationResult:
    """Return the broadcast record for the given ID, or 404."""
    result = await db.execute(
        select(BroadcastRecord).where(BroadcastRecord.id == broadcast_id)
    )
    record: BroadcastRecord | None = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    return BulkNotificationResult(
        broadcast_id=record.id,
        target=BroadcastTarget(record.target),
        title=record.title,
        recipient_count=record.recipient_count,
        sent_count=record.sent_count,
        failed_count=record.failed_count,
        created_at=record.created_at,
    )
