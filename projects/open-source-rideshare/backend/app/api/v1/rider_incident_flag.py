"""Rider incident flag endpoints.

GET    /admin/rider-incident-flags                    — list all flags, filter by status
GET    /admin/rider-incident-flags/{rider_id}         — get flag for a specific rider
POST   /admin/rider-incident-flags/{rider_id}/review  — review / clear a flag

A rider incident flag is automatically raised when INCIDENT_THRESHOLD driver
safety reports are filed against the same rider within INCIDENT_WINDOW_DAYS
days.  All endpoints are admin-only.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_incident_flag import (
    AdminReviewIncidentFlagRequest,
    FlagStatus,
    RiderIncidentFlagListResponse,
    RiderIncidentFlagResponse,
)
from app.services.rider_incident_flag import (
    admin_list_flags,
    admin_review_flag,
    get_flag,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-incident-flags"])


@router.get(
    "/admin/rider-incident-flags",
    response_model=RiderIncidentFlagListResponse,
    summary="Admin: list rider incident flags",
    description=(
        "Return all rider incident flags, optionally filtered by status.  "
        "Sorted newest-first by flagged_at.  Flags are automatically raised when a "
        "rider accumulates multiple driver safety reports."
    ),
)
async def admin_get_rider_incident_flags(
    flag_status: Optional[FlagStatus] = Query(
        None,
        alias="status",
        description="Filter by flag status (active, under_review, cleared).",
    ),
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Page size (max 200)."),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RiderIncidentFlagListResponse:
    status_val = flag_status.value if flag_status else None
    total, items = await admin_list_flags(db=db, status_filter=status_val, skip=skip, limit=limit)
    return RiderIncidentFlagListResponse(
        total=total,
        items=[RiderIncidentFlagResponse(**f) for f in items],
    )


@router.get(
    "/admin/rider-incident-flags/{rider_id}",
    response_model=RiderIncidentFlagResponse,
    summary="Admin: get incident flag for a rider",
    description="Return the current incident flag for the specified rider, if one exists.",
)
async def admin_get_rider_incident_flag(
    rider_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RiderIncidentFlagResponse:
    flag = await get_flag(db=db, rider_id=rider_id)
    if flag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No incident flag found for rider {rider_id}.",
        )
    return RiderIncidentFlagResponse(**flag)


@router.post(
    "/admin/rider-incident-flags/{rider_id}/review",
    response_model=RiderIncidentFlagResponse,
    summary="Admin: review a rider incident flag",
    description=(
        "Transition a rider incident flag to 'under_review' (investigation started) "
        "or 'cleared' (no further action needed).  Cannot manually set to 'active' — "
        "flags are raised automatically by the system."
    ),
)
async def admin_post_review_rider_incident_flag(
    rider_id: int,
    body: AdminReviewIncidentFlagRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RiderIncidentFlagResponse:
    try:
        flag = await admin_review_flag(
            db=db,
            rider_id=rider_id,
            admin_id=admin.id,
            review_status=body.review_status,
            admin_notes=body.admin_notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return RiderIncidentFlagResponse(**flag)
