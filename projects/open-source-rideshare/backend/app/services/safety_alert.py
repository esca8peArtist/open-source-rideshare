"""Community Safety Alert service layer.

Public functions:
  create_alert             — report a new hazard (driver or rider)
  get_alert                — fetch a single alert by id (raises 404 if missing)
  get_active_alerts_near   — approved alerts within a radius of a coordinate
  upvote_alert             — confirm an alert is current (409 if already voted)
  list_my_alerts           — paginated list of alerts I reported
  deactivate_alert         — reporter or admin deactivates an alert
  admin_list_alerts        — paginated admin view with optional status filter
  admin_moderate_alert     — approve or reject a pending alert
  get_platform_alert_stats — admin dashboard statistics

Geography helpers (pure, importable for testing):
  _haversine_km            — great-circle distance between two points
  _alerts_within_radius    — filter a list of alerts by proximity
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety_alert import (
    AlertType,
    ModerationStatus,
    ReporterRole,
    SafetyAlert,
    SafetyAlertUpvote,
)
from app.schemas.safety_alert import CreateSafetyAlertRequest


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class SafetyAlertError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Alert types that bypass moderation (low sensitivity)
# ---------------------------------------------------------------------------

_AUTO_APPROVE_TYPES = frozenset(
    {AlertType.road_hazard, AlertType.construction, AlertType.weather, AlertType.traffic}
)


# ---------------------------------------------------------------------------
# Geography helpers (pure)
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _alerts_within_radius(
    alerts: list[SafetyAlert],
    lat: float,
    lon: float,
    radius_km: float,
) -> list[SafetyAlert]:
    """Return alerts whose reported location is within *radius_km* of (lat, lon)."""
    result = []
    for alert in alerts:
        dist = _haversine_km(lat, lon, alert.latitude, alert.longitude)
        # Also consider the alert's own radius_meters so a large-area alert
        # (e.g. radius_meters=500) is surfaced even if its centre is slightly
        # outside the query radius.
        effective_radius_km = radius_km + (alert.radius_meters / 1000.0)
        if dist <= effective_radius_km:
            result.append(alert)
    return result


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def create_alert(
    db: AsyncSession,
    reporter_id: int,
    reporter_role: ReporterRole,
    body: CreateSafetyAlertRequest,
) -> SafetyAlert:
    """Create and persist a new safety alert.

    Low-sensitivity alert types (road hazard, construction, weather, traffic)
    are auto-approved and immediately visible.  Sensitive types (dangerous_area,
    other) enter pending status for admin review.
    """
    auto_approve = body.alert_type in _AUTO_APPROVE_TYPES
    mod_status = ModerationStatus.auto_approved if auto_approve else ModerationStatus.pending

    alert = SafetyAlert(
        reporter_id=reporter_id,
        reporter_role=reporter_role,
        alert_type=body.alert_type,
        severity=body.severity,
        latitude=body.latitude,
        longitude=body.longitude,
        radius_meters=body.radius_meters,
        description=body.description,
        expires_at=body.expires_at,
        moderation_status=mod_status,
        is_active=True,
        upvote_count=0,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


async def get_alert(db: AsyncSession, alert_id: int) -> SafetyAlert:
    """Fetch a single alert by id.  Raises SafetyAlertError(404) if not found."""
    result = await db.execute(
        select(SafetyAlert).where(SafetyAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise SafetyAlertError("Safety alert not found.", status_code=404)
    return alert


async def get_active_alerts_near(
    db: AsyncSession,
    lat: float,
    lon: float,
    radius_km: float = 5.0,
) -> list[SafetyAlert]:
    """Return active, non-expired, approved alerts within *radius_km* of a point.

    Proximity filtering is done in Python (haversine) after a DB pre-filter
    that narrows the candidate set by bounding box (±1° ≈ ±111 km) for
    performance.  For production a PostGIS spatial index would be used instead.
    """
    now = _now()
    # Bounding-box pre-filter: ±radius in degrees (1° ≈ 111 km).
    lat_margin = radius_km / 111.0
    lon_margin = radius_km / (111.0 * math.cos(math.radians(lat)) + 1e-9)

    stmt = (
        select(SafetyAlert)
        .where(
            SafetyAlert.is_active.is_(True),
            SafetyAlert.moderation_status.in_(
                [ModerationStatus.approved, ModerationStatus.auto_approved]
            ),
            SafetyAlert.latitude.between(lat - lat_margin, lat + lat_margin),
            SafetyAlert.longitude.between(lon - lon_margin, lon + lon_margin),
        )
        .where(
            (SafetyAlert.expires_at.is_(None)) | (SafetyAlert.expires_at > now)
        )
        .order_by(SafetyAlert.created_at.desc())
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    return _alerts_within_radius(candidates, lat, lon, radius_km)


async def upvote_alert(
    db: AsyncSession,
    alert_id: int,
    voter_id: int,
) -> SafetyAlert:
    """Add an upvote confirming an alert is still current.

    Idempotent at the data layer — duplicate (alert_id, voter_id) raises a
    409 SafetyAlertError rather than inserting a duplicate row.
    """
    alert = await get_alert(db, alert_id)

    if not alert.is_active:
        raise SafetyAlertError("Alert is no longer active.", status_code=409)

    # Check for existing upvote.
    existing = await db.execute(
        select(SafetyAlertUpvote).where(
            SafetyAlertUpvote.alert_id == alert_id,
            SafetyAlertUpvote.voter_id == voter_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise SafetyAlertError("You have already upvoted this alert.", status_code=409)

    upvote = SafetyAlertUpvote(alert_id=alert_id, voter_id=voter_id)
    db.add(upvote)
    alert.upvote_count += 1
    await db.commit()
    await db.refresh(alert)
    return alert


async def list_my_alerts(
    db: AsyncSession,
    reporter_id: int,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[SafetyAlert], int]:
    """Return the authenticated user's reported alerts, newest first."""
    count_result = await db.execute(
        select(func.count()).where(SafetyAlert.reporter_id == reporter_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(SafetyAlert)
        .where(SafetyAlert.reporter_id == reporter_id)
        .order_by(SafetyAlert.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def deactivate_alert(
    db: AsyncSession,
    alert_id: int,
    requesting_user_id: int,
    is_admin: bool = False,
) -> SafetyAlert:
    """Deactivate an alert.

    Reporters may deactivate their own alerts.  Admins may deactivate any alert.
    Raises 403 if a non-admin tries to deactivate another user's alert.
    """
    alert = await get_alert(db, alert_id)

    if not is_admin and alert.reporter_id != requesting_user_id:
        raise SafetyAlertError(
            "You can only deactivate your own alerts.", status_code=403
        )

    if not alert.is_active:
        raise SafetyAlertError("Alert is already inactive.", status_code=409)

    alert.is_active = False
    await db.commit()
    await db.refresh(alert)
    return alert


async def admin_list_alerts(
    db: AsyncSession,
    moderation_status: Optional[ModerationStatus] = None,
    alert_type: Optional[AlertType] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SafetyAlert], int]:
    """Admin: paginated list of all alerts with optional filters."""
    filters = []
    if moderation_status is not None:
        filters.append(SafetyAlert.moderation_status == moderation_status)
    if alert_type is not None:
        filters.append(SafetyAlert.alert_type == alert_type)

    count_stmt = select(func.count()).select_from(SafetyAlert)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(SafetyAlert)
        .order_by(SafetyAlert.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        stmt = stmt.where(*filters)
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def admin_moderate_alert(
    db: AsyncSession,
    alert_id: int,
    admin_id: int,
    action: ModerationStatus,
    note: Optional[str] = None,
) -> SafetyAlert:
    """Admin: approve or reject a pending alert.

    Only 'approved' and 'rejected' are valid moderation actions.
    """
    if action not in (ModerationStatus.approved, ModerationStatus.rejected):
        raise SafetyAlertError(
            "Moderation action must be 'approved' or 'rejected'.", status_code=422
        )

    alert = await get_alert(db, alert_id)

    alert.moderation_status = action
    alert.moderated_by = admin_id
    alert.moderated_at = _now()
    alert.moderation_note = note

    # Rejected alerts are also deactivated so they stop appearing.
    if action == ModerationStatus.rejected:
        alert.is_active = False

    await db.commit()
    await db.refresh(alert)
    return alert


async def get_platform_alert_stats(db: AsyncSession) -> dict:
    """Admin: aggregate safety alert statistics for the dashboard."""
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total = (await db.execute(select(func.count()).select_from(SafetyAlert))).scalar_one()
    active = (
        await db.execute(
            select(func.count()).where(SafetyAlert.is_active.is_(True))
        )
    ).scalar_one()
    pending = (
        await db.execute(
            select(func.count()).where(
                SafetyAlert.moderation_status == ModerationStatus.pending
            )
        )
    ).scalar_one()
    approved_today = (
        await db.execute(
            select(func.count()).where(
                SafetyAlert.moderation_status == ModerationStatus.approved,
                SafetyAlert.moderated_at >= today_start,
            )
        )
    ).scalar_one()
    rejected_today = (
        await db.execute(
            select(func.count()).where(
                SafetyAlert.moderation_status == ModerationStatus.rejected,
                SafetyAlert.moderated_at >= today_start,
            )
        )
    ).scalar_one()

    # Counts by type.
    type_rows = await db.execute(
        select(SafetyAlert.alert_type, func.count()).group_by(SafetyAlert.alert_type)
    )
    by_type = {row[0].value: row[1] for row in type_rows.all()}

    # Counts by severity.
    sev_rows = await db.execute(
        select(SafetyAlert.severity, func.count()).group_by(SafetyAlert.severity)
    )
    by_severity = {row[0].value: row[1] for row in sev_rows.all()}

    # Top upvoted active alert.
    top_result = await db.execute(
        select(SafetyAlert.id, SafetyAlert.upvote_count)
        .where(SafetyAlert.is_active.is_(True))
        .order_by(SafetyAlert.upvote_count.desc())
        .limit(1)
    )
    top_row = top_result.first()

    return {
        "total_alerts": total,
        "active_alerts": active,
        "pending_moderation": pending,
        "approved_today": approved_today,
        "rejected_today": rejected_today,
        "by_type": by_type,
        "by_severity": by_severity,
        "top_upvoted_alert_id": top_row[0] if top_row else None,
        "top_upvoted_count": top_row[1] if top_row else 0,
    }
