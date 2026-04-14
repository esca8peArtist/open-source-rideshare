"""Fare dispute & refund API endpoints.

Rider-facing:
  POST   /riders/me/rides/{ride_id}/disputes   — submit a dispute
  GET    /riders/me/disputes                    — list my disputes (paginated)
  GET    /riders/me/disputes/{dispute_id}       — single dispute detail
  DELETE /riders/me/disputes/{dispute_id}       — withdraw a pending dispute

Admin-facing:
  GET    /admin/fare-disputes                   — all disputes (paginated, filterable)
  GET    /admin/fare-disputes/summary           — aggregate stats
  GET    /admin/fare-disputes/{dispute_id}      — single dispute detail
  POST   /admin/fare-disputes/{dispute_id}/review — approve / partial / deny
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.fare_dispute import DisputeStatus
from app.models.user import User
from app.schemas.fare_dispute import (
    AdminFareDisputeListResponse,
    AdminFareDisputeResponse,
    AdminReviewRequest,
    DisputeSummaryResponse,
    FareDisputeCreateRequest,
    FareDisputeListResponse,
    FareDisputeResponse,
)
from app.services.fare_disputes import (
    DEFAULT_PAGE_SIZE,
    admin_review_dispute,
    create_dispute,
    get_dispute,
    get_dispute_for_rider,
    get_dispute_summary,
    list_all_disputes,
    list_rider_disputes,
    withdraw_dispute,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fare-disputes"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/riders/me/rides/{ride_id}/disputes",
    response_model=FareDisputeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_dispute(
    ride_id: int,
    req: FareDisputeCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a fare dispute for a completed ride."""
    dispute, err = await create_dispute(
        db,
        ride_id=ride_id,
        rider_user_id=current_user.id,
        category=req.category,
        description=req.description,
        disputed_amount=req.disputed_amount,
    )
    if err:
        code = status.HTTP_404_NOT_FOUND if "not found" in err.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=err)
    return dispute


@router.get(
    "/riders/me/disputes",
    response_model=FareDisputeListResponse,
)
async def list_my_disputes(
    status_filter: DisputeStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current rider's fare disputes."""
    disputes, total = await list_rider_disputes(
        db,
        current_user.id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return FareDisputeListResponse(
        disputes=disputes,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/riders/me/disputes/{dispute_id}",
    response_model=FareDisputeResponse,
)
async def get_my_dispute(
    dispute_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single fare dispute belonging to the current rider."""
    dispute = await get_dispute_for_rider(db, dispute_id, current_user.id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    return dispute


@router.delete(
    "/riders/me/disputes/{dispute_id}",
    response_model=FareDisputeResponse,
)
async def withdraw_my_dispute(
    dispute_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw a pending fare dispute."""
    dispute, err = await withdraw_dispute(db, dispute_id, current_user.id)
    if err:
        code = status.HTTP_404_NOT_FOUND if err == "Dispute not found" else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=err)
    return dispute


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/admin/fare-disputes/summary",
    response_model=DisputeSummaryResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_get_dispute_summary(
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stats across all fare disputes."""
    summary = await get_dispute_summary(db)
    return DisputeSummaryResponse(**summary)


@router.get(
    "/admin/fare-disputes",
    response_model=AdminFareDisputeListResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_list_disputes(
    status_filter: DisputeStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all fare disputes (admin). Filterable by status."""
    disputes, total = await list_all_disputes(
        db,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return AdminFareDisputeListResponse(
        disputes=disputes,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/admin/fare-disputes/{dispute_id}",
    response_model=AdminFareDisputeResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_get_dispute(
    dispute_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single fare dispute (admin view)."""
    dispute = await get_dispute(db, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    return dispute


@router.post(
    "/admin/fare-disputes/{dispute_id}/review",
    response_model=AdminFareDisputeResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_review(
    dispute_id: int,
    req: AdminReviewRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve, issue partial refund, or deny a fare dispute."""
    dispute, err = await admin_review_dispute(
        db,
        dispute_id,
        current_user.id,
        decision=req.decision,
        admin_notes=req.admin_notes,
        refund_amount=req.refund_amount,
        stripe_refund_id=req.stripe_refund_id,
    )
    if err:
        code = status.HTTP_404_NOT_FOUND if "not found" in err.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=err)
    return dispute
