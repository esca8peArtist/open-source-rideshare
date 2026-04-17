"""Corporate Fleet Incident Report endpoints.

Fleet members log vehicle incidents and fleet admins manage them through
review, resolution, and closure.

Member endpoints (any authenticated account member):
  POST /corporate/{account_id}/fleet/incidents              — create incident → 201
  GET  /corporate/{account_id}/fleet/incidents              — list incidents (filterable)
  GET  /corporate/{account_id}/fleet/incidents/{report_id}  — get one incident

Admin endpoints (account admins only):
  PUT    /corporate/{account_id}/fleet/incidents/{report_id}          — update
  PUT    /corporate/{account_id}/fleet/incidents/{report_id}/resolve   — resolve
  PUT    /corporate/{account_id}/fleet/incidents/{report_id}/close     — close
  DELETE /corporate/{account_id}/fleet/incidents/{report_id}           — delete → 204

Summary endpoints:
  GET /corporate/{account_id}/fleet/incidents/summary/vehicle/{vehicle_id} — vehicle summary
  GET /corporate/{account_id}/fleet/incidents/summary/account              — account summary

Platform-admin endpoints:
  GET /platform/corporate/fleet/incidents/summary — platform-wide overview
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_incident import (
    FleetIncidentStatus,
    FleetIncidentType,
)
from app.models.user import User
from app.schemas.corporate_fleet_incident import (
    AccountIncidentSummaryResponse,
    IncidentReportCreate,
    IncidentReportResponse,
    IncidentReportUpdate,
    PlatformIncidentOverviewResponse,
    VehicleIncidentSummaryResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_incident_service import (
    close_incident_report,
    create_incident_report,
    delete_incident_report,
    get_account_incident_summary,
    get_incident_report,
    get_platform_admin_incident_overview,
    get_vehicle_incident_summary,
    list_incident_reports,
    resolve_incident_report,
    update_incident_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Incidents"])


# ---------------------------------------------------------------------------
# Member: create incident report
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet/incidents",
    response_model=IncidentReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a new fleet vehicle incident report (member or admin)",
)
async def create_incident_report_endpoint(
    account_id: int,
    data: IncidentReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a new incident report for a fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the account does not exist.
    """
    await get_account(db, account_id)
    return await create_incident_report(db, account_id, user.id, data)


# ---------------------------------------------------------------------------
# Member: list incident reports  <- MUST be before /{report_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/incidents",
    response_model=List[IncidentReportResponse],
    summary="List fleet incident reports for an account (member or admin)",
)
async def list_incident_reports_endpoint(
    account_id: int,
    vehicle_id: Optional[uuid.UUID] = Query(
        None, description="Filter to a specific vehicle"
    ),
    status: Optional[FleetIncidentStatus] = Query(
        None, description="Filter by lifecycle status"
    ),
    incident_type: Optional[FleetIncidentType] = Query(
        None, description="Filter by incident type"
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of incident reports for the account.

    Ordered by incident_date descending.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_incident_reports(
        db,
        account_id,
        vehicle_id=vehicle_id,
        status=status,
        incident_type=incident_type,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Summary: vehicle incident summary  <- MUST be before /{report_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/incidents/summary/vehicle/{vehicle_id}",
    response_model=VehicleIncidentSummaryResponse,
    summary="Get incident summary for a specific fleet vehicle",
)
async def get_vehicle_incident_summary_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate incident statistics for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_vehicle_incident_summary(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Summary: account incident summary  <- MUST be before /{report_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/incidents/summary/account",
    response_model=AccountIncidentSummaryResponse,
    summary="Get account-wide fleet incident summary (admin only)",
)
async def get_account_incident_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return account-wide aggregate incident statistics.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_account_incident_summary(db, account_id)


# ---------------------------------------------------------------------------
# Member: get single incident report
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/incidents/{report_id}",
    response_model=IncidentReportResponse,
    summary="Get a single fleet incident report",
)
async def get_incident_report_endpoint(
    account_id: int,
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single incident report by ID.

    Returns 404 if the report does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_incident_report(db, account_id, report_id)


# ---------------------------------------------------------------------------
# Admin: update incident report
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet/incidents/{report_id}",
    response_model=IncidentReportResponse,
    summary="Update a fleet incident report (admin only)",
)
async def update_incident_report_endpoint(
    account_id: int,
    report_id: uuid.UUID,
    data: IncidentReportUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a fleet incident report.

    Returns 404 if the report does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_incident_report(db, account_id, report_id, data)


# ---------------------------------------------------------------------------
# Admin: resolve incident report
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet/incidents/{report_id}/resolve",
    response_model=IncidentReportResponse,
    summary="Resolve a fleet incident report (admin only)",
)
async def resolve_incident_report_endpoint(
    account_id: int,
    report_id: uuid.UUID,
    resolution_notes: Optional[str] = Body(None, embed=True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a fleet incident report as resolved.

    Sets status to resolved and records resolved_at timestamp.
    Returns 404 if the report does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await resolve_incident_report(db, account_id, report_id, resolution_notes)


# ---------------------------------------------------------------------------
# Admin: close incident report
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet/incidents/{report_id}/close",
    response_model=IncidentReportResponse,
    summary="Close a resolved fleet incident report (admin only)",
)
async def close_incident_report_endpoint(
    account_id: int,
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close a fleet incident report.

    Only reports with status=resolved may be closed.
    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report is not in resolved status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await close_incident_report(db, account_id, report_id)


# ---------------------------------------------------------------------------
# Admin: delete incident report
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet/incidents/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fleet incident report (admin only)",
)
async def delete_incident_report_endpoint(
    account_id: int,
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a fleet incident report.

    Only reports with status=reported or resolved may be deleted.
    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report status prevents deletion.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_incident_report(db, account_id, report_id)


# ---------------------------------------------------------------------------
# Platform-admin: platform-wide incident overview
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet/incidents/summary",
    response_model=PlatformIncidentOverviewResponse,
    summary="Admin: get platform-wide fleet incident overview",
)
async def get_platform_incident_overview_endpoint(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate incident statistics across all corporate accounts.

    Platform admin only.
    """
    return await get_platform_admin_incident_overview(db)
