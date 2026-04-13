"""Lost and Found API endpoints.

Rider endpoints (auth required, own reports only):
  POST /lost-found/report          — report a lost item
  GET  /lost-found/my-reports      — list my reports
  GET  /lost-found/{report_id}     — get single report

Driver endpoints (driver auth required):
  POST /drivers/me/found-items     — report a found item
  GET  /drivers/me/found-items     — list items I've found

Admin endpoints (admin auth required):
  GET  /admin/lost-found                           — list all reports (filterable)
  GET  /admin/lost-found/{report_id}               — get report details
  POST /admin/lost-found/{report_id}/match         — link found + lost reports
  POST /admin/lost-found/{report_id}/resolve       — close out a report
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.lost_found import LostItemCategory, LostItemStatus
from app.models.user import User, UserRole
from app.schemas.lost_found import (
    LostItemReportCreate,
    LostItemReportResponse,
    MatchReportRequest,
    ResolveReportRequest,
)
from app.services.lost_found import (
    LostFoundError,
    RESOLVABLE_STATUSES,
    create_report,
    get_report,
    list_all_reports,
    list_reports_for_user,
    match_reports,
    resolve_report,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lost-found"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.post("/lost-found/report", response_model=LostItemReportResponse, status_code=status.HTTP_201_CREATED)
async def report_lost_item(
    req: LostItemReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report a lost item (something left in a vehicle).

    Any authenticated user may submit a lost report. If ride_id is provided
    the user must be a participant in that ride.
    """
    try:
        report = await create_report(
            db,
            reporter_id=user.id,
            reporter_type="rider",
            description=req.description,
            category=req.category,
            ride_id=req.ride_id,
            color=req.color,
            contact_phone=req.contact_phone,
            contact_email=req.contact_email,
        )
    except LostFoundError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(report)
    return report


@router.get("/lost-found/my-reports", response_model=list[LostItemReportResponse])
async def list_my_lost_reports(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated user's lost item reports, newest first."""
    reports = await list_reports_for_user(db, reporter_id=user.id, limit=limit, offset=offset)
    return reports


@router.get("/lost-found/{report_id}", response_model=LostItemReportResponse)
async def get_lost_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single lost/found report.

    Riders and drivers may only view their own reports. Admins can view any.
    """
    try:
        report = await get_report(
            db,
            report_id=report_id,
            requesting_user_id=user.id,
            is_admin=(user.role == UserRole.ADMIN),
        )
    except LostFoundError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return report


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/found-items",
    response_model=LostItemReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_found_item(
    req: LostItemReportCreate,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Report a found item (something a passenger left behind).

    Requires driver role. If ride_id is provided the driver must have
    driven that ride.
    """
    try:
        report = await create_report(
            db,
            reporter_id=driver.id,
            reporter_type="driver",
            description=req.description,
            category=req.category,
            ride_id=req.ride_id,
            color=req.color,
            contact_phone=req.contact_phone,
            contact_email=req.contact_email,
        )
    except LostFoundError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(report)
    return report


@router.get("/drivers/me/found-items", response_model=list[LostItemReportResponse])
async def list_my_found_items(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """List items the authenticated driver has reported as found, newest first."""
    reports = await list_reports_for_user(
        db,
        reporter_id=driver.id,
        reporter_type="driver",
        limit=limit,
        offset=offset,
    )
    return reports


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/lost-found", response_model=list[LostItemReportResponse])
async def admin_list_reports(
    status_filter: LostItemStatus | None = Query(None, alias="status", description="Filter by status"),
    category_filter: LostItemCategory | None = Query(None, alias="category", description="Filter by category"),
    date_from: datetime | None = Query(None, description="Created at or after this datetime (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Created at or before this datetime (ISO 8601)"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all lost/found reports with optional filters.

    Supports filtering by status, category, and date range.
    Results are ordered newest first.
    """
    reports = await list_all_reports(
        db,
        status_filter=status_filter,
        category_filter=category_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return reports


@router.get("/admin/lost-found/{report_id}", response_model=LostItemReportResponse)
async def admin_get_report(
    report_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: get details for a specific lost/found report."""
    try:
        report = await get_report(db, report_id=report_id, requesting_user_id=0, is_admin=True)
    except LostFoundError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return report


@router.post("/admin/lost-found/{report_id}/match", response_model=LostItemReportResponse)
async def admin_match_reports(
    report_id: int,
    req: MatchReportRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: link a found report to a lost report.

    Sets both reports to MATCHED status and records the admin who made the
    match. Triggers notifications to both reporters.
    """
    try:
        report_a, _ = await match_reports(
            db,
            report_id=report_id,
            matched_report_id=req.matched_report_id,
            admin_id=admin.id,
        )
    except LostFoundError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(report_a)
    return report_a


@router.post("/admin/lost-found/{report_id}/resolve", response_model=LostItemReportResponse)
async def admin_resolve_report(
    report_id: int,
    req: ResolveReportRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: close out a report with a terminal status.

    Valid terminal statuses: returned, donated, discarded.
    RETURNED requires the report to have been matched first.
    """
    if req.status not in RESOLVABLE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(s.value for s in RESOLVABLE_STATUSES)}",
        )

    try:
        report = await resolve_report(
            db,
            report_id=report_id,
            new_status=req.status,
            admin_id=admin.id,
            resolution_notes=req.resolution_notes,
        )
    except LostFoundError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(report)
    return report
