"""Corporate Vehicle Incident Report endpoints.

Fleet managers document incidents involving company vehicles and track them
through a resolution workflow: draft → reported → under_review → resolved → closed.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/incidents  — list vehicle incidents
  GET  /corporate/{account_id}/vehicle-incidents/{incident_id}        — get one report
  POST /corporate/{account_id}/vehicle-incidents/                     — create report (draft)
  PUT  /corporate/{account_id}/vehicle-incidents/{incident_id}        — update report
  POST /corporate/{account_id}/vehicle-incidents/{incident_id}/submit — submit draft → reported

Admin endpoints (account admins only):
  POST /corporate/{account_id}/vehicle-incidents/{incident_id}/review  — mark under review
  POST /corporate/{account_id}/vehicle-incidents/{incident_id}/resolve — resolve
  POST /corporate/{account_id}/vehicle-incidents/{incident_id}/close   — close
  GET  /corporate/{account_id}/vehicle-incidents/                      — list all (filtered)
  GET  /corporate/{account_id}/vehicle-incidents/summary               — summary stats

Platform-admin endpoints:
  GET  /platform/corporate/vehicle-incidents/                          — cross-account list
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_vehicle_incident import IncidentStatus, IncidentType
from app.models.user import User
from app.schemas.corporate_vehicle_incidents import (
    IncidentReportCreate,
    IncidentReportResponse,
    IncidentReportUpdate,
    IncidentSummaryResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_vehicle_incident_service import (
    close_incident,
    create_incident_report,
    get_incident_report,
    get_incident_summary,
    list_account_incidents,
    list_all_platform,
    list_vehicle_incidents,
    mark_under_review,
    resolve_incident,
    submit_incident,
    update_incident_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Vehicle Incidents"])


# ---------------------------------------------------------------------------
# Member: list incidents for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/incidents",
    response_model=List[IncidentReportResponse],
    summary="List incident reports for a fleet vehicle",
)
async def list_vehicle_incidents_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    incident_type: Optional[IncidentType] = Query(
        None, description="Filter by incident category"
    ),
    incident_status: Optional[IncidentStatus] = Query(
        None, description="Filter by workflow status"
    ),
    from_date: Optional[date] = Query(None, description="Lower bound on incident_date"),
    to_date: Optional[date] = Query(None, description="Upper bound on incident_date"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all incident reports for a specific fleet vehicle.

    Ordered by incident_date descending.  Returns 404 if the vehicle does
    not exist in this account.  Any authenticated account member may call
    this endpoint.
    """
    await get_account(db, account_id)
    return await list_vehicle_incidents(
        db,
        account_id,
        vehicle_id,
        incident_type=incident_type,
        incident_status=incident_status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Admin: get incident summary  ← MUST be before /{incident_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-incidents/summary",
    response_model=IncidentSummaryResponse,
    summary="Get incident statistics for the account (admin only)",
)
async def get_incident_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate incident counts and damage totals for the account.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_incident_summary(db, account_id)


# ---------------------------------------------------------------------------
# Admin: list all account incidents  ← MUST be before /{incident_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-incidents/",
    response_model=List[IncidentReportResponse],
    summary="List all incident reports for the account (admin only)",
)
async def list_account_incidents_endpoint(
    account_id: int,
    incident_type: Optional[IncidentType] = Query(
        None, description="Filter by incident category"
    ),
    incident_status: Optional[IncidentStatus] = Query(
        None, description="Filter by workflow status"
    ),
    from_date: Optional[date] = Query(None, description="Lower bound on incident_date"),
    to_date: Optional[date] = Query(None, description="Upper bound on incident_date"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of incident reports for the account.

    Ordered by incident_date descending.  Only account admins may call
    this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_incidents(
        db,
        account_id,
        incident_type=incident_type,
        incident_status=incident_status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Member: create incident report  ← MUST be before /{incident_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-incidents/",
    response_model=IncidentReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vehicle incident report",
)
async def create_incident_report_endpoint(
    account_id: int,
    data: IncidentReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new vehicle incident report in draft status.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the vehicle is inactive.
    Returns 404 if the insurance_policy_id provided does not exist in this account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await create_incident_report(db, account_id, data)


# ---------------------------------------------------------------------------
# Member: get single incident report
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-incidents/{incident_id}",
    response_model=IncidentReportResponse,
    summary="Get a single incident report",
)
async def get_incident_report_endpoint(
    account_id: int,
    incident_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single incident report by ID.

    Returns 404 if the report does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_incident_report(db, account_id, incident_id)


# ---------------------------------------------------------------------------
# Member: update incident report
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/vehicle-incidents/{incident_id}",
    response_model=IncidentReportResponse,
    summary="Update an incident report",
)
async def update_incident_report_endpoint(
    account_id: int,
    incident_id: uuid.UUID,
    data: IncidentReportUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a vehicle incident report.

    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report is in resolved or closed status.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await update_incident_report(db, account_id, incident_id, data)


# ---------------------------------------------------------------------------
# Member: submit incident (draft → reported)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-incidents/{incident_id}/submit",
    response_model=IncidentReportResponse,
    summary="Submit a draft incident report",
)
async def submit_incident_endpoint(
    account_id: int,
    incident_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move an incident report from draft to reported status.

    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report is not in draft status.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await submit_incident(db, account_id, incident_id, reported_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: mark under review (reported → under_review)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-incidents/{incident_id}/review",
    response_model=IncidentReportResponse,
    summary="Mark an incident report as under review (admin only)",
)
async def mark_under_review_endpoint(
    account_id: int,
    incident_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move an incident report from reported to under_review status.

    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report is not in reported status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await mark_under_review(db, account_id, incident_id, reviewed_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: resolve incident (under_review → resolved)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-incidents/{incident_id}/resolve",
    response_model=IncidentReportResponse,
    summary="Resolve an incident report (admin only)",
)
async def resolve_incident_endpoint(
    account_id: int,
    incident_id: uuid.UUID,
    notes: Optional[str] = Query(None, description="Optional resolution notes"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move an incident report from under_review to resolved status.

    Sets resolved_at to the current UTC time.
    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report is not in under_review status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await resolve_incident(
        db, account_id, incident_id, reviewed_by_id=user.id, notes=notes
    )


# ---------------------------------------------------------------------------
# Admin: close incident (resolved → closed)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-incidents/{incident_id}/close",
    response_model=IncidentReportResponse,
    summary="Close a resolved incident report (admin only)",
)
async def close_incident_endpoint(
    account_id: int,
    incident_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move an incident report from resolved to closed status.

    Returns 404 if the report does not exist or belongs to a different account.
    Returns 409 if the report is not in resolved status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await close_incident(db, account_id, incident_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all incident reports across all accounts
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-incidents/",
    response_model=List[IncidentReportResponse],
    summary="Admin: list all vehicle incident reports across all accounts",
)
async def admin_list_all_incidents(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    incident_type: Optional[IncidentType] = Query(
        None, description="Filter by incident category"
    ),
    incident_status: Optional[IncidentStatus] = Query(
        None, description="Filter by workflow status"
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return vehicle incident reports across all corporate accounts.

    Platform admin only.  Optionally filter by account_id, incident_type,
    or incident_status.
    """
    return await list_all_platform(
        db,
        account_id=account_id,
        incident_type=incident_type,
        incident_status=incident_status,
        limit=limit,
        offset=offset,
    )
