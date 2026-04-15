"""Pydantic schemas for Community Safety Alert endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.safety_alert import (
    AlertSeverity,
    AlertType,
    ModerationStatus,
    ReporterRole,
    SafetyAlert,
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateSafetyAlertRequest(BaseModel):
    """Body for reporting a new safety hazard or concern."""

    alert_type: AlertType
    severity: AlertSeverity = AlertSeverity.medium

    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    radius_meters: float = Field(
        100.0, gt=0, le=10_000,
        description="Approximate area affected in metres (default 100 m, max 10 km).",
    )

    description: Optional[str] = Field(None, max_length=1000)

    expires_at: Optional[datetime] = Field(
        None,
        description="Optional expiry — alert deactivates automatically after this time.",
    )

    @field_validator("expires_at", mode="before")
    @classmethod
    def expires_must_be_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None:
            from datetime import timezone
            now = datetime.now(tz=timezone.utc)
            # Make naive datetimes UTC-aware for comparison.
            compare = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if compare <= now:
                raise ValueError("expires_at must be in the future.")
        return v


class AdminModerateAlertRequest(BaseModel):
    """Admin body to approve or reject a pending safety alert."""

    action: ModerationStatus = Field(
        ...,
        description="Only 'approved' or 'rejected' are valid moderation actions.",
    )
    note: Optional[str] = Field(None, max_length=500)

    @field_validator("action")
    @classmethod
    def action_must_be_moderation_decision(cls, v: ModerationStatus) -> ModerationStatus:
        if v not in (ModerationStatus.approved, ModerationStatus.rejected):
            raise ValueError("action must be 'approved' or 'rejected'.")
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SafetyAlertResponse(BaseModel):
    """Public-facing alert representation."""

    id: int
    reporter_role: ReporterRole
    alert_type: AlertType
    severity: AlertSeverity
    latitude: float
    longitude: float
    radius_meters: float
    description: Optional[str]
    is_active: bool
    expires_at: Optional[datetime]
    moderation_status: ModerationStatus
    upvote_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_alert(cls, alert: SafetyAlert) -> "SafetyAlertResponse":
        return cls(
            id=alert.id,
            reporter_role=alert.reporter_role,
            alert_type=alert.alert_type,
            severity=alert.severity,
            latitude=alert.latitude,
            longitude=alert.longitude,
            radius_meters=alert.radius_meters,
            description=alert.description,
            is_active=alert.is_active,
            expires_at=alert.expires_at,
            moderation_status=alert.moderation_status,
            upvote_count=alert.upvote_count,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )


class SafetyAlertDetailResponse(SafetyAlertResponse):
    """Extended view including reporter id (shown to reporter and admins)."""

    reporter_id: int
    moderated_by: Optional[int]
    moderated_at: Optional[datetime]
    moderation_note: Optional[str]

    @classmethod
    def from_alert(cls, alert: SafetyAlert) -> "SafetyAlertDetailResponse":  # type: ignore[override]
        base = SafetyAlertResponse.from_alert(alert)
        return cls(
            **base.model_dump(),
            reporter_id=alert.reporter_id,
            moderated_by=alert.moderated_by,
            moderated_at=alert.moderated_at,
            moderation_note=alert.moderation_note,
        )


class SafetyAlertListResponse(BaseModel):
    """Paginated list of alerts."""

    alerts: list[SafetyAlertResponse]
    total: int


class SafetyAlertDetailListResponse(BaseModel):
    """Paginated list of detailed alerts (admin view)."""

    alerts: list[SafetyAlertDetailResponse]
    total: int


class SafetyAlertStatsResponse(BaseModel):
    """Platform-wide safety alert statistics for the admin dashboard."""

    total_alerts: int
    active_alerts: int
    pending_moderation: int
    approved_today: int
    rejected_today: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    top_upvoted_alert_id: Optional[int]
    top_upvoted_count: int
