"""Service layer for platform announcements.

Provides:
  - create_announcement         — admin creates a draft
  - update_announcement         — admin updates draft/published announcement
  - publish_announcement        — admin publishes a draft (sets published_at)
  - unpublish_announcement      — admin reverts a published announcement to draft
  - delete_announcement         — admin soft-deletes (is_active=False)
  - list_announcements_for_user — filtered list for the calling user's role
  - get_announcement            — fetch single announcement by id
  - mark_viewed                 — upsert an AnnouncementView row (viewed_at)
  - acknowledge_announcement    — set acknowledged_at on an existing view
  - get_pending_acknowledgments — unacknowledged critical announcements for user
  - admin_list_all              — paginated list across all statuses
  - get_announcement_stats      — view/ack counts for an announcement
  - get_announcement_views      — paginated per-user view records
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.announcement import (
    AnnouncementAudience,
    AnnouncementView,
    PlatformAnnouncement,
)
from app.models.user import User, UserRole
from app.schemas.announcement import (
    AnnouncementStats,
    AnnouncementViewRecord,
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AnnouncementError(HTTPException):
    """Domain error for the announcements service."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _audience_for_role(role: UserRole) -> list[AnnouncementAudience]:
    """Return the audience values a user with *role* can see.

    ALL is always included. MEMBERS is available to both drivers and riders
    (any registered platform user counts as a cooperative member candidate).
    """
    base = [AnnouncementAudience.ALL, AnnouncementAudience.MEMBERS]
    if role == UserRole.DRIVER:
        base.append(AnnouncementAudience.DRIVERS)
    elif role == UserRole.RIDER:
        base.append(AnnouncementAudience.RIDERS)
    # ADMIN sees everything; handled by admin_list_all
    return base


# ---------------------------------------------------------------------------
# Admin write operations
# ---------------------------------------------------------------------------


async def create_announcement(
    db: AsyncSession,
    admin_id: int,
    req: CreateAnnouncementRequest,
) -> PlatformAnnouncement:
    """Create a new draft announcement."""
    ann = PlatformAnnouncement(
        title=req.title,
        body=req.body,
        audience=req.audience,
        priority=req.priority,
        requires_acknowledgment=req.requires_acknowledgment,
        expires_at=req.expires_at,
        created_by=admin_id,
        is_active=True,
        published_at=None,
    )
    db.add(ann)
    await db.flush()
    return ann


async def update_announcement(
    db: AsyncSession,
    ann_id: int,
    req: UpdateAnnouncementRequest,
) -> PlatformAnnouncement:
    """Update a draft or published announcement."""
    ann = await _get_or_404(db, ann_id)
    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(ann, field, value)
    await db.flush()
    return ann


async def publish_announcement(
    db: AsyncSession,
    ann_id: int,
) -> PlatformAnnouncement:
    """Publish a draft announcement (set published_at to now)."""
    ann = await _get_or_404(db, ann_id)
    if ann.published_at is not None:
        raise AnnouncementError(409, "Announcement is already published")
    ann.published_at = _now()
    await db.flush()
    return ann


async def unpublish_announcement(
    db: AsyncSession,
    ann_id: int,
) -> PlatformAnnouncement:
    """Revert a published announcement to draft (clear published_at)."""
    ann = await _get_or_404(db, ann_id)
    if ann.published_at is None:
        raise AnnouncementError(409, "Announcement is not published")
    ann.published_at = None
    await db.flush()
    return ann


async def delete_announcement(
    db: AsyncSession,
    ann_id: int,
) -> None:
    """Soft-delete an announcement (is_active=False). Hides it everywhere."""
    ann = await _get_or_404(db, ann_id)
    ann.is_active = False
    await db.flush()


# ---------------------------------------------------------------------------
# Read operations (user-facing)
# ---------------------------------------------------------------------------


async def get_announcement(
    db: AsyncSession,
    ann_id: int,
) -> PlatformAnnouncement:
    """Return a single announcement by id (any status — for admin use)."""
    return await _get_or_404(db, ann_id)


async def list_announcements_for_user(
    db: AsyncSession,
    user: User,
    limit: int = 50,
    offset: int = 0,
) -> list[PlatformAnnouncement]:
    """Return published, non-expired, active announcements visible to *user*.

    Filters by audience based on the user's role.
    """
    audiences = _audience_for_role(user.role)
    now = _now()
    q = (
        select(PlatformAnnouncement)
        .where(
            PlatformAnnouncement.is_active.is_(True),
            PlatformAnnouncement.published_at.isnot(None),
            PlatformAnnouncement.published_at <= now,
            PlatformAnnouncement.audience.in_(audiences),
        )
        .where(
            # expires_at IS NULL (never expires) OR expires_at > now
            (PlatformAnnouncement.expires_at.is_(None))
            | (PlatformAnnouncement.expires_at > now)
        )
        .order_by(PlatformAnnouncement.published_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_public_announcements(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> list[PlatformAnnouncement]:
    """Return published, non-expired announcements with audience=ALL.

    No auth required — used for marketing/landing page feeds.
    """
    now = _now()
    q = (
        select(PlatformAnnouncement)
        .where(
            PlatformAnnouncement.is_active.is_(True),
            PlatformAnnouncement.published_at.isnot(None),
            PlatformAnnouncement.published_at <= now,
            PlatformAnnouncement.audience == AnnouncementAudience.ALL,
        )
        .where(
            (PlatformAnnouncement.expires_at.is_(None))
            | (PlatformAnnouncement.expires_at > now)
        )
        .order_by(PlatformAnnouncement.published_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def admin_list_all(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    active_only: bool = False,
) -> list[PlatformAnnouncement]:
    """Admin: paginated list of all announcements, newest first."""
    q = select(PlatformAnnouncement).order_by(
        PlatformAnnouncement.created_at.desc()
    )
    if active_only:
        q = q.where(PlatformAnnouncement.is_active.is_(True))
    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# View and acknowledgment operations
# ---------------------------------------------------------------------------


async def mark_viewed(
    db: AsyncSession,
    user_id: int,
    ann_id: int,
) -> AnnouncementView:
    """Upsert an AnnouncementView row — create on first call, no-op on repeat.

    Returns the (possibly existing) view record.
    """
    # Ensure announcement exists
    await _get_or_404(db, ann_id)

    result = await db.execute(
        select(AnnouncementView).where(
            AnnouncementView.announcement_id == ann_id,
            AnnouncementView.user_id == user_id,
        )
    )
    view = result.scalar_one_or_none()
    if view is None:
        view = AnnouncementView(
            announcement_id=ann_id,
            user_id=user_id,
            viewed_at=_now(),
        )
        db.add(view)
        await db.flush()
    return view


async def acknowledge_announcement(
    db: AsyncSession,
    user_id: int,
    ann_id: int,
) -> AnnouncementView:
    """Mark an announcement as acknowledged by this user.

    Creates a view record if one doesn't exist yet (viewing and acking in one step).
    Raises 409 if already acknowledged.
    """
    ann = await _get_or_404(db, ann_id)
    if not ann.requires_acknowledgment:
        raise AnnouncementError(
            422,
            "This announcement does not require acknowledgment",
        )

    result = await db.execute(
        select(AnnouncementView).where(
            AnnouncementView.announcement_id == ann_id,
            AnnouncementView.user_id == user_id,
        )
    )
    view = result.scalar_one_or_none()
    if view is None:
        now = _now()
        view = AnnouncementView(
            announcement_id=ann_id,
            user_id=user_id,
            viewed_at=now,
            acknowledged_at=now,
        )
        db.add(view)
        await db.flush()
        return view

    if view.acknowledged_at is not None:
        raise AnnouncementError(409, "Announcement already acknowledged")
    view.acknowledged_at = _now()
    await db.flush()
    return view


async def get_pending_acknowledgments(
    db: AsyncSession,
    user: User,
) -> list[PlatformAnnouncement]:
    """Return published critical announcements the user has not yet acknowledged.

    Used to surface a "you have unacknowledged critical notices" banner.
    """
    audiences = _audience_for_role(user.role)
    now = _now()

    # Subquery: announcement IDs already acknowledged by this user
    acked_subq = (
        select(AnnouncementView.announcement_id)
        .where(
            AnnouncementView.user_id == user.id,
            AnnouncementView.acknowledged_at.isnot(None),
        )
        .scalar_subquery()
    )

    q = (
        select(PlatformAnnouncement)
        .where(
            PlatformAnnouncement.is_active.is_(True),
            PlatformAnnouncement.published_at.isnot(None),
            PlatformAnnouncement.published_at <= now,
            PlatformAnnouncement.requires_acknowledgment.is_(True),
            PlatformAnnouncement.audience.in_(audiences),
            PlatformAnnouncement.id.not_in(acked_subq),
        )
        .where(
            (PlatformAnnouncement.expires_at.is_(None))
            | (PlatformAnnouncement.expires_at > now)
        )
        .order_by(PlatformAnnouncement.published_at.asc())
    )
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin analytics
# ---------------------------------------------------------------------------


async def get_announcement_stats(
    db: AsyncSession,
    ann_id: int,
) -> AnnouncementStats:
    """Return total view and acknowledgment counts for a single announcement."""
    await _get_or_404(db, ann_id)

    view_count_result = await db.execute(
        select(func.count(AnnouncementView.id)).where(
            AnnouncementView.announcement_id == ann_id
        )
    )
    total_views = view_count_result.scalar_one() or 0

    ack_count_result = await db.execute(
        select(func.count(AnnouncementView.id)).where(
            AnnouncementView.announcement_id == ann_id,
            AnnouncementView.acknowledged_at.isnot(None),
        )
    )
    total_acks = ack_count_result.scalar_one() or 0

    return AnnouncementStats(
        announcement_id=ann_id,
        total_views=total_views,
        total_acknowledgments=total_acks,
    )


async def get_announcement_views(
    db: AsyncSession,
    ann_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[AnnouncementViewRecord]:
    """Admin: paginated list of per-user view records for an announcement."""
    await _get_or_404(db, ann_id)
    q = (
        select(AnnouncementView)
        .where(AnnouncementView.announcement_id == ann_id)
        .order_by(AnnouncementView.viewed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        AnnouncementViewRecord(
            user_id=r.user_id,
            viewed_at=r.viewed_at,
            acknowledged_at=r.acknowledged_at,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_or_404(
    db: AsyncSession,
    ann_id: int,
) -> PlatformAnnouncement:
    result = await db.execute(
        select(PlatformAnnouncement).where(PlatformAnnouncement.id == ann_id)
    )
    ann = result.scalar_one_or_none()
    if ann is None:
        raise AnnouncementError(404, "Announcement not found")
    return ann
