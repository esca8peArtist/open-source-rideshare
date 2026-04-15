"""Driver incident reporting endpoints.

Driver endpoints:
  POST /drivers/me/incidents                    — report a new incident
  GET  /drivers/me/incidents                    — paginated list of own incidents
  GET  /drivers/me/incidents/{id}               — get a specific incident
  PUT  /drivers/me/incidents/{id}               — update (while still submitted)

Admin endpoints:
  GET  /admin/driver-incidents                  — list all incidents (filterable)
  GET  /admin/driver-incidents/{id}             — get any incident
  PUT  /admin/driver-incidents/{id}/review      — start review
  PUT  /admin/driver-incidents/{id}/resolve     — resolve
  PUT  /admin/driver-incidents/{id}/dismiss     — dismiss
  GET  /admin/driver-incidents/summary          — platform-wide statistics
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.driver_incident import IncidentSeverity, IncidentStatus, IncidentType
from app.models.user import User
from app.schemas.driver_incident import (
    AdminIncidentDismiss,
    AdminIncidentListOut,
    AdminIncidentResolve,
    AdminIncidentReview,
    AdminIncidentRow,
    AdminIncidentSummary,
    DriverIncidentCreate,
    DriverIncidentListOut,
    DriverIncidentResponse,
    DriverIncidentUpdate,
)
from app.services.driver_incident import (
    admin_dismiss_incident,
    admin_get_incident,
    admin_incident_summary,
    admin_list_incidents,
    admin_resolve_incident,
    admin_start_review,
    create_incident,
    get_driver_incident,
    list_driver_incidents,
    update_driver_incident,
)

router = APIRouter(tags=["driver-incidents"])


# ---------------------------------------------------------------------------
# Driver — incident management
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/incidents",
    response_model=DriverIncidentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def driver_report_incident(
    body: DriverIncidentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report a safety incident.

    Drivers can report incidents involving a passenger — harassment, threats,
    property damage, theft, unsafe behavior, accidents, or other concerns.
    Unlike Uber/Lyft, every report is tracked with a transparent status and
    receives a formal admin review.
    """
    report = await create_incident(
        db,
        driver_id=user.id,
        incident_type=body.incident_type,
        severity=body.severity,
        description=body.description,
        ride_id=body.ride_id,
        evidence_urls=body.evidence_urls,
    )
    return DriverIncidentResponse.from_orm_model(report)


@router.get(
    "/drivers/me/incidents",
    response_model=DriverIncidentListOut,
)
async def driver_list_incidents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of the authenticated driver's incident reports, newest first."""
    reports, total = await list_driver_incidents(db, user.id, limit=limit, offset=offset)
    return DriverIncidentListOut(
        incidents=[DriverIncidentResponse.from_orm_model(r) for r in reports],
        total=total,
    )


@router.get(
    "/drivers/me/incidents/{incident_id}",
    response_model=DriverIncidentResponse,
)
async def driver_get_incident(
    incident_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific incident report (must belong to the authenticated driver)."""
    report = await get_driver_incident(db, incident_id, user.id)
    return DriverIncidentResponse.from_orm_model(report)


@router.put(
    "/drivers/me/incidents/{incident_id}",
    response_model=DriverIncidentResponse,
)
async def driver_update_incident(
    incident_id: int,
    body: DriverIncidentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an incident report.

    Only allowed while the report is in *submitted* status (before admin
    review begins).  Drivers can correct their description or add evidence.
    """
    report = await update_driver_incident(
        db,
        incident_id=incident_id,
        driver_id=user.id,
        description=body.description,
        evidence_urls=body.evidence_urls,
    )
    return DriverIncidentResponse.from_orm_model(report)


# ---------------------------------------------------------------------------
# Admin — incident oversight
# ---------------------------------------------------------------------------


@router.get(
    "/admin/driver-incidents/summary",
    response_model=AdminIncidentSummary,
    dependencies=[Depends(require_admin)],
)
async def admin_get_incident_summary(
    db: AsyncSession = Depends(get_db),
):
    """Admin: platform-wide incident statistics.

    Shows totals broken down by status, severity, and incident type.
    The *critical_open* field surfaces the most urgent incidents.
    """
    data = await admin_incident_summary(db)
    return AdminIncidentSummary(**data)


@router.get(
    "/admin/driver-incidents",
    response_model=AdminIncidentListOut,
    dependencies=[Depends(require_admin)],
)
async def admin_list_driver_incidents(
    incident_status: Optional[IncidentStatus] = Query(None, alias="status"),
    severity: Optional[IncidentSeverity] = Query(None),
    incident_type: Optional[IncidentType] = Query(None, alias="type"),
    driver_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all incident reports with optional filters.

    Use *status=submitted* to find new reports needing triage.
    Use *severity=critical* to surface highest-priority reports.
    """
    reports, total = await admin_list_incidents(
        db,
        incident_status=incident_status,
        severity=severity,
        incident_type=incident_type,
        driver_id=driver_id,
        limit=limit,
        offset=offset,
    )
    rows = [
        AdminIncidentRow(
            **DriverIncidentResponse.from_orm_model(r).model_dump(),
            driver_name=None,
        )
        for r in reports
    ]
    return AdminIncidentListOut(incidents=rows, total=total)


@router.get(
    "/admin/driver-incidents/{incident_id}",
    response_model=AdminIncidentRow,
    dependencies=[Depends(require_admin)],
)
async def admin_get_driver_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Admin: get any incident report by ID."""
    report = await admin_get_incident(db, incident_id)
    return AdminIncidentRow(
        **DriverIncidentResponse.from_orm_model(report).model_dump(),
        driver_name=None,
    )


@router.put(
    "/admin/driver-incidents/{incident_id}/review",
    response_model=DriverIncidentResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_review_incident(
    incident_id: int,
    body: AdminIncidentReview,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: mark an incident as under review.

    Transitions the report from *submitted* → *under_review* and records
    which admin picked it up.
    """
    report = await admin_start_review(db, incident_id, user.id, body.admin_note)
    return DriverIncidentResponse.from_orm_model(report)


@router.put(
    "/admin/driver-incidents/{incident_id}/resolve",
    response_model=DriverIncidentResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_resolve_driver_incident(
    incident_id: int,
    body: AdminIncidentResolve,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: resolve an incident.

    Marks the report as *resolved* and records the admin's note on the
    outcome.  Drivers can see this resolution, providing the transparency
    that Uber/Lyft typically lack.
    """
    report = await admin_resolve_incident(db, incident_id, user.id, body.admin_note)
    return DriverIncidentResponse.from_orm_model(report)


@router.put(
    "/admin/driver-incidents/{incident_id}/dismiss",
    response_model=DriverIncidentResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_dismiss_driver_incident(
    incident_id: int,
    body: AdminIncidentDismiss,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: dismiss an incident report.

    Use for reports that are duplicates, outside scope, or made in bad faith.
    A dismissal note is required so drivers understand why the report was
    closed without action — cooperative accountability in both directions.
    """
    report = await admin_dismiss_incident(db, incident_id, user.id, body.admin_note)
    return DriverIncidentResponse.from_orm_model(report)
