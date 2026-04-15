"""Pydantic schemas for platform announcements."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.announcement import AnnouncementAudience, AnnouncementPriority


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateAnnouncementRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    body: str = Field(..., min_length=10)
    audience: AnnouncementAudience = AnnouncementAudience.ALL
    priority: AnnouncementPriority = AnnouncementPriority.NORMAL
    requires_acknowledgment: bool = False
    expires_at: datetime | None = None


class UpdateAnnouncementRequest(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    body: str | None = Field(None, min_length=10)
    audience: AnnouncementAudience | None = None
    priority: AnnouncementPriority | None = None
    requires_acknowledgment: bool | None = None
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AnnouncementSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    audience: AnnouncementAudience
    priority: AnnouncementPriority
    requires_acknowledgment: bool
    published_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime


class AnnouncementDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    audience: AnnouncementAudience
    priority: AnnouncementPriority
    requires_acknowledgment: bool
    published_at: datetime | None
    expires_at: datetime | None
    created_by: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AnnouncementWithViewStatus(AnnouncementDetail):
    """Announcement detail with the current user's view/ack status appended."""
    viewed: bool
    acknowledged: bool
    acknowledged_at: datetime | None


class AnnouncementViewResponse(BaseModel):
    """Response for view/acknowledge actions."""
    announcement_id: int
    user_id: int
    viewed_at: datetime
    acknowledged_at: datetime | None


class AnnouncementStats(BaseModel):
    """Admin view: engagement counts for a single announcement."""
    announcement_id: int
    total_views: int
    total_acknowledgments: int


class AnnouncementViewRecord(BaseModel):
    """Single view record — used in admin paginated view list."""
    user_id: int
    viewed_at: datetime
    acknowledged_at: datetime | None
