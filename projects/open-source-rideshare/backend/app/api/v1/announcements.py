"""Platform Announcements API.

A persistent cooperative news/update feed — distinct from bulk_notifications
(fire-and-forget push). Announcements are browsable, filterable by audience,
and support explicit acknowledgment for critical policy notices.

Public endpoints (no auth):
  GET  /announcements                            — published ALL-audience announcements

Authenticated endpoints (any logged-in user):
  GET  /me/announcements                         — my audience-filtered feed
  GET  /me/announcements/pending                 — unacknowledged critical items
  POST /me/announcements/{id}/view               — mark viewed
  POST /me/announcements/{id}/acknowledge        — acknowledge critical announcement

Admin endpoints:
  POST /admin/announcements                      — create draft
  GET  /admin/announcements                      — list all (paginated)
  GET  /admin/announcements/{id}                 — detail + stats
  PUT  /admin/announcements/{id}                 — update
  POST /admin/announcements/{id}/publish         — publish draft
  POST /admin/announcements/{id}/unpublish       — revert to draft
  DELETE /admin/announcements/{id}               — soft-delete
  GET  /admin/announcements/{id}/views           — view/ack records
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementDetail,
    AnnouncementStats,
    AnnouncementSummary,
    AnnouncementViewRecord,
    AnnouncementViewResponse,
    AnnouncementWithViewStatus,
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)
from app.services.announcements import (
    acknowledge_announcement,
    admin_list_all,
    create_announcement,
    delete_announcement,
    get_announcement,
    get_announcement_stats,
    get_announcement_views,
    get_pending_acknowledgments,
    list_announcements_for_user,
    list_public_announcements,
    mark_viewed,
    publish_announcement,
    unpublish_announcement,
    update_announcement,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["announcements"])


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


@router.get(
    "/announcements",
    response_model=list[AnnouncementSummary],
    summary="List public announcements",
    description="Published announcements with audience=ALL. No authentication required.",
)
async def list_public(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await list_public_announcements(db, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Authenticated user endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/me/announcements",
    response_model=list[AnnouncementSummary],
    summary="My announcement feed",
    description="Published announcements filtered to my audience (role-based).",
)
async def my_announcements(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_announcements_for_user(db, user, limit=limit, offset=offset)


@router.get(
    "/me/announcements/pending",
    response_model=list[AnnouncementSummary],
    summary="Pending critical acknowledgments",
    description="Critical announcements requiring my acknowledgment that I haven't acknowledged yet.",
)
async def pending_acknowledgments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_pending_acknowledgments(db, user)


@router.post(
    "/me/announcements/{ann_id}/view",
    response_model=AnnouncementViewResponse,
    summary="Mark an announcement as viewed",
)
async def view_announcement(
    ann_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    view = await mark_viewed(db, user.id, ann_id)
    await db.commit()
    return AnnouncementViewResponse(
        announcement_id=view.announcement_id,
        user_id=view.user_id,
        viewed_at=view.viewed_at,
        acknowledged_at=view.acknowledged_at,
    )


@router.post(
    "/me/announcements/{ann_id}/acknowledge",
    response_model=AnnouncementViewResponse,
    summary="Acknowledge a critical announcement",
)
async def acknowledge(
    ann_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    view = await acknowledge_announcement(db, user.id, ann_id)
    await db.commit()
    return AnnouncementViewResponse(
        announcement_id=view.announcement_id,
        user_id=view.user_id,
        viewed_at=view.viewed_at,
        acknowledged_at=view.acknowledged_at,
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/admin/announcements",
    response_model=AnnouncementDetail,
    status_code=201,
    summary="Create a draft announcement",
    dependencies=[Depends(require_admin)],
)
async def admin_create(
    req: CreateAnnouncementRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ann = await create_announcement(db, user.id, req)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.get(
    "/admin/announcements",
    response_model=list[AnnouncementDetail],
    summary="List all announcements",
    dependencies=[Depends(require_admin)],
)
async def admin_list(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await admin_list_all(db, limit=limit, offset=offset, active_only=active_only)


@router.get(
    "/admin/announcements/{ann_id}",
    response_model=AnnouncementDetail,
    summary="Get announcement detail",
    dependencies=[Depends(require_admin)],
)
async def admin_get(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await get_announcement(db, ann_id)


@router.get(
    "/admin/announcements/{ann_id}/stats",
    response_model=AnnouncementStats,
    summary="Get view/acknowledgment stats",
    dependencies=[Depends(require_admin)],
)
async def admin_stats(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await get_announcement_stats(db, ann_id)


@router.put(
    "/admin/announcements/{ann_id}",
    response_model=AnnouncementDetail,
    summary="Update an announcement",
    dependencies=[Depends(require_admin)],
)
async def admin_update(
    ann_id: int,
    req: UpdateAnnouncementRequest,
    db: AsyncSession = Depends(get_db),
):
    ann = await update_announcement(db, ann_id, req)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.post(
    "/admin/announcements/{ann_id}/publish",
    response_model=AnnouncementDetail,
    summary="Publish a draft announcement",
    dependencies=[Depends(require_admin)],
)
async def admin_publish(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
):
    ann = await publish_announcement(db, ann_id)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.post(
    "/admin/announcements/{ann_id}/unpublish",
    response_model=AnnouncementDetail,
    summary="Revert a published announcement to draft",
    dependencies=[Depends(require_admin)],
)
async def admin_unpublish(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
):
    ann = await unpublish_announcement(db, ann_id)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.delete(
    "/admin/announcements/{ann_id}",
    status_code=204,
    summary="Soft-delete an announcement",
    dependencies=[Depends(require_admin)],
)
async def admin_delete(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
):
    await delete_announcement(db, ann_id)
    await db.commit()


@router.get(
    "/admin/announcements/{ann_id}/views",
    response_model=list[AnnouncementViewRecord],
    summary="List view/acknowledgment records for an announcement",
    dependencies=[Depends(require_admin)],
)
async def admin_view_records(
    ann_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await get_announcement_views(db, ann_id, limit=limit, offset=offset)
