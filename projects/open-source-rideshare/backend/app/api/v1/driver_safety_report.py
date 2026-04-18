"""Post-ride driver safety report endpoints.

POST   /drivers/me/safety-reports                        — file a safety report
GET    /drivers/me/safety-reports                        — list own reports (paginated)
GET    /drivers/me/safety-reports/{report_id}            — get specific report
GET    /admin/driver-safety-reports                      — admin: list all reports
GET    /admin/driver-safety-reports/stats                — admin: aggregate statistics
POST   /admin/driver-safety-reports/{report_id}/review   — admin: review a report

Drivers can file at most one safety report per ride.  Reports are routed to
admin review (PENDING → REVIEWED / ESCALATED / CLOSED).  Only rides in
COMPLETED status qualify — no reporting during or before the ride.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_safety_report import (
    AdminReviewDriverReportRequest,
    DriverReportCategory,
    DriverReportStatus,
    DriverSafetyReportCreate,
    DriverSafetyReportListResponse,
    DriverSafetyReportResponse,
    DriverSafetyReportStats,
)
from app.services.driver_safety_report import (
    admin_list_reports,
    admin_review_report,
    create_report,
    get_driver_safety_report_stats,
    get_report,
    list_driver_reports,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-safety-reports"])


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/safety-reports",
    response_model=DriverSafetyReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="File a post-ride driver safety report",
    description=(
        "File a safety concern about a rider after a completed ride.  "
        "One report per ride is permitted.  The ride must be in COMPLETED status "
        "and the authenticated user must be the driver on that ride.\n\n"
        "Reports are immediately visible to platform admins and feed into rider "
        "quality and safety workflows."
    ),
)
async def post_create_driver_safety_report(
    body: DriverSafetyReportCreate,
    driver: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyReportResponse:
    """File a safety report for a completed ride."""
    from sqlalchemy import select
    from app.models.ride import Ride, RideStatus

    result = await db.execute(
        select(Ride).where(
            Ride.id == body.ride_id,
            Ride.driver_id == driver.id,
            Ride.status == RideStatus.COMPLETED,
        )
    )
    ride = result.scalar_one_or_none()
    if ride is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Ride not found or not eligible for a safety report. "
                "Only your completed rides can be reported."
            ),
        )

    try:
        report = await create_report(
            db=db,
            driver_id=driver.id,
            ride_id=ride.id,
            rider_id=ride.rider_id,
            category=body.category,
            description=body.description,
            location_lat=body.location_lat,
            location_lng=body.location_lng,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return DriverSafetyReportResponse(**report)


@router.get(
    "/drivers/me/safety-reports",
    response_model=DriverSafetyReportListResponse,
    summary="List my safety reports",
    description="Return all safety reports filed by the authenticated driver, newest-first.",
)
async def get_list_driver_safety_reports(
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)."),
    driver: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyReportListResponse:
    total, items = await list_driver_reports(db=db, driver_id=driver.id, skip=skip, limit=limit)
    return DriverSafetyReportListResponse(
        total=total,
        items=[DriverSafetyReportResponse(**r) for r in items],
    )


@router.get(
    "/drivers/me/safety-reports/{report_id}",
    response_model=DriverSafetyReportResponse,
    summary="Get a driver safety report",
    description="Retrieve a specific safety report filed by the authenticated driver.",
)
async def get_driver_safety_report(
    report_id: str,
    driver: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyReportResponse:
    report = await get_report(db=db, driver_id=driver.id, report_id=report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Safety report not found.",
        )
    return DriverSafetyReportResponse(**report)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/driver-safety-reports",
    response_model=DriverSafetyReportListResponse,
    summary="Admin: list all driver safety reports",
    description=(
        "Return all driver safety reports across all drivers, optionally filtered by status "
        "and/or category.  Sorted newest-first."
    ),
)
async def admin_get_driver_safety_reports(
    report_status: Optional[DriverReportStatus] = Query(
        None,
        alias="status",
        description="Filter by report status.",
    ),
    category: Optional[DriverReportCategory] = Query(
        None,
        description="Filter by report category.",
    ),
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Page size (max 200)."),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyReportListResponse:
    status_val = report_status.value if report_status else None
    category_val = category.value if category else None
    total, items = await admin_list_reports(
        db=db,
        status_filter=status_val,
        category_filter=category_val,
        skip=skip,
        limit=limit,
    )
    return DriverSafetyReportListResponse(
        total=total,
        items=[DriverSafetyReportResponse(**r) for r in items],
    )


@router.get(
    "/admin/driver-safety-reports/stats",
    response_model=DriverSafetyReportStats,
    summary="Admin: driver safety report aggregate statistics",
    description=(
        "Return aggregate statistics across all driver safety reports: total count, "
        "counts by status and category, escalation rate, rolling 7-day and 30-day "
        "counts, and average resolution time for resolved reports."
    ),
)
async def admin_get_driver_safety_report_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyReportStats:
    stats = await get_driver_safety_report_stats(db=db)
    return DriverSafetyReportStats(**stats)


@router.post(
    "/admin/driver-safety-reports/{report_id}/review",
    response_model=DriverSafetyReportResponse,
    summary="Admin: review a driver safety report",
    description=(
        "Mark a driver safety report as REVIEWED, ESCALATED, or CLOSED with optional notes.  "
        "Only PENDING reports can be reviewed.  Status cannot be reset to 'pending'."
    ),
)
async def admin_post_review_driver_safety_report(
    report_id: str,
    body: AdminReviewDriverReportRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyReportResponse:
    try:
        report = await admin_review_report(
            db=db,
            report_id=report_id,
            admin_id=admin.id,
            review_status=body.review_status,
            admin_notes=body.admin_notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return DriverSafetyReportResponse(**report)
