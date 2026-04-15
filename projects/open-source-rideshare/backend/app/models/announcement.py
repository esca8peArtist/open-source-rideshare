"""Platform announcement and acknowledgment models.

Two tables:
  platform_announcements — persistent cooperative news/updates posted by admins
  announcement_views     — per-user view and acknowledgment records

Announcements are a persistent feed, distinct from bulk_notifications (fire-and-forget
push). Riders and drivers browse announcements at their own pace; critical ones require
explicit acknowledgment (e.g., policy changes, regulatory notices).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AnnouncementAudience(str, enum.Enum):
    ALL = "all"          # visible to every authenticated user
    DRIVERS = "drivers"  # visible only to drivers
    RIDERS = "riders"    # visible only to riders
    MEMBERS = "members"  # visible only to cooperative members (drivers + riders who joined)


class AnnouncementPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"  # requires_acknowledgment should be True for these


class PlatformAnnouncement(Base):
    """A persistent cooperative announcement or news item.

    Admins create announcements and publish them. Published announcements
    appear in the relevant audience's feed. Critical announcements require
    explicit acknowledgment from each user before they can be dismissed.
    """

    __tablename__ = "platform_announcements"

    __table_args__ = (
        Index("ix_announcement_audience_published", "audience", "published_at"),
        Index("ix_announcement_priority_active", "priority", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[AnnouncementAudience] = mapped_column(
        Enum(AnnouncementAudience), nullable=False, default=AnnouncementAudience.ALL
    )
    priority: Mapped[AnnouncementPriority] = mapped_column(
        Enum(AnnouncementPriority), nullable=False, default=AnnouncementPriority.NORMAL
    )
    requires_acknowledgment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # NULL = unpublished draft; set by publish action
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # NULL = never expires
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    # Soft-delete: is_active=False hides from all queries
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    creator = relationship("User", foreign_keys=[created_by])
    views: Mapped[list["AnnouncementView"]] = relationship(
        "AnnouncementView",
        back_populates="announcement",
        cascade="all, delete-orphan",
    )


class AnnouncementView(Base):
    """Per-user view and acknowledgment record for a platform announcement.

    One row per (announcement, user) pair. Created on first view.
    acknowledged_at is set when the user explicitly acknowledges the announcement.
    """

    __tablename__ = "announcement_views"

    __table_args__ = (
        UniqueConstraint("announcement_id", "user_id", name="uq_announcement_view_user"),
        Index("ix_ann_view_user_acked", "user_id", "acknowledged_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("platform_announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    announcement = relationship("PlatformAnnouncement", back_populates="views")
