"""Post-ride rider safety report endpoints.

POST   /riders/me/safety-reports                        — file a safety report
GET    /riders/me/safety-reports                        — list own reports (paginated)
GET    /riders/me/safety-reports/{report_id}            — get specific report
GET    /admin/safety-reports                            — admin: list all reports
POST   /admin/safety-reports/{report_id}/review         — admin: review a report

Riders can file at most one safety report per ride.  Reports are routed to
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
from app.schemas.rider_safety_report import (
    AdminReviewReportRequest,
    SafetyReportCategory,
    SafetyReportCreate,
    SafetyReportListResponse,
    SafetyReportResponse,
    SafetyReportStatus,
)
from app.services.rider_safety_report import (
    admin_list_reports,
    admin_review_report,
    create_report,
    get_report,
    list_rider_reports,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-safety-reports"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/safety-reports",
    response_model=SafetyReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="File a post-ride safety report",
    description=(
        "File a safety concern about a driver after a completed ride.  "
        "One report per ride is permitted.  The ride must be in COMPLETED status "
        "and the authenticated user must be the rider on that ride.\n\n"
        "Reports are immediately visible to platform admins and feed into driver "
        "quality and safety workflows."
    ),
)
async def post_create_safety_report(
    body: SafetyReportCreate,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyReportResponse:
    """File a safety report for a completed ride."""
    from sqlalchemy import select
    from app.models.ride import Ride, RideStatus

    result = await db.execute(
        select(Ride).where(
            Ride.id == body.ride_id,
            Ride.rider_id == rider.id,
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
            rider_id=rider.id,
            ride_id=ride.id,
            driver_id=ride.driver_id,
            category=body.category,
            description=body.description,
            location_lat=body.location_lat,
            location_lng=body.location_lng,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return SafetyReportResponse(**report)


@router.get(
    "/riders/me/safety-reports",
    response_model=SafetyReportListResponse,
    summary="List my safety reports",
    description="Return all safety reports filed by the authenticated rider, newest-first.",
)
async def get_list_rider_safety_reports(
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)."),
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyReportListResponse:
    total, items = await list_rider_reports(db=db, rider_id=rider.id, skip=skip, limit=limit)
    return SafetyReportListResponse(
        total=total,
        items=[SafetyReportResponse(**r) for r in items],
    )


@router.get(
    "/riders/me/safety-reports/{report_id}",
    response_model=SafetyReportResponse,
    summary="Get a safety report",
    description="Retrieve a specific safety report filed by the authenticated rider.",
)
async def get_rider_safety_report(
    report_id: str,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyReportResponse:
    report = await get_report(db=db, rider_id=rider.id, report_id=report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Safety report not found.",
        )
    return SafetyReportResponse(**report)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/safety-reports",
    response_model=SafetyReportListResponse,
    summary="Admin: list all safety reports",
    description=(
        "Return all safety reports across all riders, optionally filtered by status "
        "and/or category.  Sorted newest-first."
    ),
)
async def admin_get_safety_reports(
    report_status: Optional[SafetyReportStatus] = Query(
        None,
        alias="status",
        description="Filter by report status.",
    ),
    category: Optional[SafetyReportCategory] = Query(
        None,
        description="Filter by report category.",
    ),
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Page size (max 200)."),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SafetyReportListResponse:
    status_val = report_status.value if report_status else None
    category_val = category.value if category else None
    total, items = await admin_list_reports(
        db=db,
        status_filter=status_val,
        category_filter=category_val,
        skip=skip,
        limit=limit,
    )
    return SafetyReportListResponse(
        total=total,
        items=[SafetyReportResponse(**r) for r in items],
    )


@router.post(
    "/admin/safety-reports/{report_id}/review",
    response_model=SafetyReportResponse,
    summary="Admin: review a safety report",
    description=(
        "Mark a safety report as REVIEWED, ESCALATED, or CLOSED with optional notes.  "
        "Only PENDING reports can be reviewed.  Status cannot be reset to 'pending'."
    ),
)
async def admin_post_review_safety_report(
    report_id: str,
    body: AdminReviewReportRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SafetyReportResponse:
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

    return SafetyReportResponse(**report)
