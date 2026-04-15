"""Pydantic schemas for Driver Certification Badge endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.driver_certification import BadgeType

# Re-export for convenience
__all__ = [
    "BadgeType",
    "DriverBadgeResponse",
    "DriverBadgeListResponse",
    "AwardBadgeRequest",
    "RevokeBadgeRequest",
    "BadgeEligibilityResult",
    "BadgeEligibilityReport",
    "BadgeStats",
]


class DriverBadgeResponse(BaseModel):
    """A single driver certification badge."""

    model_config = {"from_attributes": True}

    id: int
    driver_id: int
    badge_type: BadgeType
    is_active: bool
    awarded_at: datetime
    awarded_by: Optional[int] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = None
    notes: Optional[str] = None


class DriverBadgeListResponse(BaseModel):
    """Paginated list of driver badges with summary counts."""

    model_config = {"from_attributes": True}

    badges: list[DriverBadgeResponse]
    total: int
    active_count: int


class AwardBadgeRequest(BaseModel):
    """Admin request body to award a badge to a driver."""

    badge_type: BadgeType
    notes: Optional[str] = None


class RevokeBadgeRequest(BaseModel):
    """Admin request body to revoke a badge from a driver."""

    notes: Optional[str] = None


class BadgeEligibilityResult(BaseModel):
    """Eligibility check result for a single badge type."""

    badge_type: BadgeType
    is_eligible: bool
    reason: str


class BadgeEligibilityReport(BaseModel):
    """Full eligibility report for a driver, with any newly awarded badges."""

    driver_id: int
    results: list[BadgeEligibilityResult]
    newly_awarded: list[BadgeType]


class BadgeDriverSummary(BaseModel):
    """Driver badge count for top-drivers list."""

    driver_id: int
    badge_count: int


class BadgeStats(BaseModel):
    """Platform-wide badge statistics for admin dashboard."""

    total_active: int
    by_type: dict[str, int]
    top_drivers: list[BadgeDriverSummary]
