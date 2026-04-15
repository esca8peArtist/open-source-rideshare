"""Community Safety Alert endpoints.

Auth-user (driver or rider) endpoints:
  POST   /safety-alerts                   — report a new hazard
  GET    /safety-alerts/nearby            — approved alerts near a coordinate
  GET    /safety-alerts/me                — alerts I have reported
  POST   /safety-alerts/{id}/upvote       — confirm an alert is still current
  DELETE /safety-alerts/{id}              — deactivate my own alert

Admin endpoints:
  GET    /admin/safety-alerts             — all alerts with optional filters
  GET    /admin/safety-alerts/{id}        — single alert detail
  POST   /admin/safety-alerts/{id}/moderate — approve or reject a pending alert
  GET    /admin/safety-alerts/stats       — platform-wide statistics
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.safety_alert import AlertType, ModerationStatus, ReporterRole
from app.models.user import User
from app.schemas.safety_alert import (
    AdminModerateAlertRequest,
    CreateSafetyAlertRequest,
    SafetyAlertDetailListResponse,
    SafetyAlertDetailResponse,
    SafetyAlertListResponse,
    SafetyAlertResponse,
    SafetyAlertStatsResponse,
)
from app.services.safety_alert import (
    SafetyAlertError,
    admin_list_alerts,
    admin_moderate_alert,
    create_alert,
    deactivate_alert,
    get_active_alerts_near,
    get_alert,
    get_platform_alert_stats,
    list_my_alerts,
    upvote_alert,
)

router = APIRouter(tags=["safety-alerts"])


def _http_error(exc: SafetyAlertError):
    from fastapi import HTTPException
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------------------
# Auth-user: reporting and browsing
# ---------------------------------------------------------------------------


@router.post(
    "/safety-alerts",
    response_model=SafetyAlertDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_safety_alert(
    body: CreateSafetyAlertRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report a new safety hazard or concern.

    Low-sensitivity types (road_hazard, construction, weather, traffic) are
    auto-approved and immediately visible.  Sensitive reports (dangerous_area,
    other) enter moderation.

    Cooperative differentiator: Uber/Lyft have no community-powered safety
    layer — safety data is siloed and never shared back to drivers or riders.
    """
    role = ReporterRole.driver if getattr(user, "is_driver", False) else ReporterRole.rider
    alert = await create_alert(db, user.id, role, body)
    return SafetyAlertDetailResponse.from_alert(alert)


@router.get(
    "/safety-alerts/nearby",
    response_model=SafetyAlertListResponse,
)
async def get_nearby_alerts(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Observer latitude"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Observer longitude"),
    radius_km: float = Query(5.0, gt=0, le=50, description="Search radius in kilometres"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active, approved safety alerts within *radius_km* of a point.

    Intended for the driver app to surface hazards along a planned route and
    for riders to see conditions near their pickup/dropoff.
    """
    alerts = await get_active_alerts_near(db, lat, lon, radius_km)
    return SafetyAlertListResponse(
        alerts=[SafetyAlertResponse.from_alert(a) for a in alerts],
        total=len(alerts),
    )


@router.get(
    "/safety-alerts/me",
    response_model=SafetyAlertDetailListResponse,
)
async def my_safety_alerts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the alerts reported by the authenticated user."""
    alerts, total = await list_my_alerts(db, user.id, limit=limit, offset=offset)
    return SafetyAlertDetailListResponse(
        alerts=[SafetyAlertDetailResponse.from_alert(a) for a in alerts],
        total=total,
    )


@router.post(
    "/safety-alerts/{alert_id}/upvote",
    response_model=SafetyAlertResponse,
)
async def upvote_safety_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm that a safety alert is still current.

    One upvote per user per alert — returns 409 if already voted.
    High upvote counts surface the alert more prominently in the driver app.
    """
    try:
        alert = await upvote_alert(db, alert_id, user.id)
    except SafetyAlertError as e:
        _http_error(e)
    return SafetyAlertResponse.from_alert(alert)


@router.delete(
    "/safety-alerts/{alert_id}",
    response_model=SafetyAlertDetailResponse,
)
async def deactivate_my_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an alert you reported.

    Use when the hazard has been resolved (road cleared, construction ended, etc.).
    Returns 403 if the alert was reported by a different user.
    """
    try:
        alert = await deactivate_alert(db, alert_id, user.id, is_admin=False)
    except SafetyAlertError as e:
        _http_error(e)
    return SafetyAlertDetailResponse.from_alert(alert)


# ---------------------------------------------------------------------------
# Admin: oversight and moderation
# ---------------------------------------------------------------------------


@router.get(
    "/admin/safety-alerts",
    response_model=SafetyAlertDetailListResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_list_safety_alerts(
    moderation_status: Optional[ModerationStatus] = Query(None, alias="status"),
    alert_type: Optional[AlertType] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all safety alerts with optional filters.

    Use *status=pending* to review unmoderated reports.
    """
    alerts, total = await admin_list_alerts(
        db,
        moderation_status=moderation_status,
        alert_type=alert_type,
        limit=limit,
        offset=offset,
    )
    return SafetyAlertDetailListResponse(
        alerts=[SafetyAlertDetailResponse.from_alert(a) for a in alerts],
        total=total,
    )


@router.get(
    "/admin/safety-alerts/stats",
    response_model=SafetyAlertStatsResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_safety_alert_stats(
    db: AsyncSession = Depends(get_db),
):
    """Admin: platform-wide safety alert statistics.

    Includes counts by type and severity, pending moderation backlog, and the
    most-upvoted active alert (a signal of high community concern).
    """
    stats = await get_platform_alert_stats(db)
    return SafetyAlertStatsResponse(**stats)


@router.get(
    "/admin/safety-alerts/{alert_id}",
    response_model=SafetyAlertDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_get_safety_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Admin: full detail view for a single safety alert."""
    try:
        alert = await get_alert(db, alert_id)
    except SafetyAlertError as e:
        _http_error(e)
    return SafetyAlertDetailResponse.from_alert(alert)


@router.post(
    "/admin/safety-alerts/{alert_id}/moderate",
    response_model=SafetyAlertDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_moderate_safety_alert(
    alert_id: int,
    body: AdminModerateAlertRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: approve or reject a pending safety alert.

    Approved alerts become visible to nearby drivers and riders.
    Rejected alerts are deactivated and hidden from all users.
    """
    try:
        alert = await admin_moderate_alert(
            db, alert_id, user.id, action=body.action, note=body.note
        )
    except SafetyAlertError as e:
        _http_error(e)
    return SafetyAlertDetailResponse.from_alert(alert)


@router.delete(
    "/admin/safety-alerts/{alert_id}",
    response_model=SafetyAlertDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_deactivate_safety_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: force-deactivate any active safety alert."""
    try:
        alert = await deactivate_alert(db, alert_id, user.id, is_admin=True)
    except SafetyAlertError as e:
        _http_error(e)
    return SafetyAlertDetailResponse.from_alert(alert)
