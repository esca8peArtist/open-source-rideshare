"""Ride dispute endpoints.

POST   /rides/{ride_id}/disputes            — file a dispute (rider or driver)
GET    /rides/{ride_id}/disputes            — list disputes for a ride
GET    /me/disputes                         — list my disputes (paginated)
GET    /me/disputes/received                — disputes filed against me on my rides
GET    /me/disputes/{dispute_id}            — get a specific dispute
GET    /admin/disputes                      — admin: list all disputes
PATCH  /admin/disputes/{dispute_id}/review  — admin: move to under_review
POST   /admin/disputes/{dispute_id}/resolve — admin: resolve with notes + refund
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.feedback import (
    DisputeCreate,
    DisputeListResponse,
    DisputeRespondentReply,
    DisputeResolve,
    DisputeResponse,
)
from app.services.disputes import (
    add_respondent_reply,
    file_dispute,
    get_dispute,
    get_disputes_against_user,
    get_user_disputes,
    list_disputes,
    resolve_dispute,
    update_dispute_status,
)

router = APIRouter(tags=["disputes"])


def _dispute_response(d) -> DisputeResponse:
    return DisputeResponse(
        id=d.id,
        ride_id=d.ride_id,
        filed_by=d.filed_by,
        dispute_type=d.dispute_type.value if hasattr(d.dispute_type, "value") else d.dispute_type,
        status=d.status.value if hasattr(d.status, "value") else d.status,
        description=d.description,
        resolution_notes=d.resolution_notes,
        resolved_by=d.resolved_by,
        refund_amount=d.refund_amount,
        created_at=d.created_at,
        updated_at=d.updated_at,
        resolved_at=d.resolved_at,
        respondent_response=d.respondent_response if isinstance(d.respondent_response, str) else None,
        respondent_responded_at=d.respondent_responded_at if isinstance(d.respondent_responded_at, datetime) else None,
    )


# ---------------------------------------------------------------------------
# Rider / driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/rides/{ride_id}/disputes",
    response_model=DisputeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="File a dispute on a completed or cancelled ride",
)
async def post_dispute(
    ride_id: int,
    body: DisputeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """File a dispute as the rider or driver on the ride.

    Only one open dispute per participant per ride is allowed.
    The ride must be COMPLETED or CANCELLED.
    """
    try:
        dispute = await file_dispute(
            ride_id=ride_id,
            user_id=user.id,
            dispute_type=body.dispute_type,
            description=body.description,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return _dispute_response(dispute)


@router.get(
    "/rides/{ride_id}/disputes",
    response_model=DisputeListResponse,
    summary="List disputes for a ride",
)
async def list_ride_disputes(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisputeListResponse:
    """Return all disputes filed on a specific ride.

    Accessible to the ride's rider, its driver, or admin.
    """
    from sqlalchemy import select
    from app.models.feedback import Dispute

    if user.role.value == "admin":
        items, total = await list_disputes(db)
        ride_items = [d for d in items if d.ride_id == ride_id]
        return DisputeListResponse(disputes=[_dispute_response(d) for d in ride_items], total=len(ride_items))

    from sqlalchemy import select as sa_select
    from app.models.ride import Ride

    result = await db.execute(sa_select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view disputes for this ride")

    result = await db.execute(
        sa_select(Dispute).where(Dispute.ride_id == ride_id).order_by(Dispute.created_at.desc())
    )
    items = list(result.scalars().all())
    return DisputeListResponse(disputes=[_dispute_response(d) for d in items], total=len(items))


@router.get(
    "/me/disputes",
    response_model=DisputeListResponse,
    summary="List my disputes",
)
async def get_my_disputes(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisputeListResponse:
    """Paginated list of disputes the caller has filed."""
    items, total = await get_user_disputes(user_id=user.id, db=db, limit=limit, offset=offset)
    return DisputeListResponse(disputes=[_dispute_response(d) for d in items], total=total)


@router.get(
    "/me/disputes/received",
    response_model=DisputeListResponse,
    summary="List disputes filed against me",
)
async def get_disputes_received(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisputeListResponse:
    """Paginated list of disputes other participants filed on rides where the caller was involved.

    Drivers use this to see disputes filed against them on trips they drove.
    Riders see disputes a driver filed on a ride they took.
    """
    items, total = await get_disputes_against_user(user_id=user.id, db=db, limit=limit, offset=offset)
    return DisputeListResponse(disputes=[_dispute_response(d) for d in items], total=total)


@router.get(
    "/me/disputes/{dispute_id}",
    response_model=DisputeResponse,
    summary="Get a specific dispute I filed",
)
async def get_my_dispute(
    dispute_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """Get a single dispute by ID. Returns 404 if not found or if the caller didn't file it."""
    dispute = await get_dispute(dispute_id, db)
    if not dispute or dispute.filed_by != user.id:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return _dispute_response(dispute)


@router.post(
    "/disputes/{dispute_id}/response",
    response_model=DisputeResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit your response to a dispute filed against you",
)
async def post_dispute_response(
    dispute_id: int,
    body: DisputeRespondentReply,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """The non-filing participant of a ride can submit one response while the dispute is open or under review."""
    try:
        dispute = await add_respondent_reply(dispute_id, user.id, body.response, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _dispute_response(dispute)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/disputes",
    response_model=DisputeListResponse,
    summary="Admin: list all disputes",
)
async def admin_list_disputes(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DisputeListResponse:
    """List all disputes with optional status filter. Admin only."""
    valid_statuses = {
        "open", "under_review", "resolved_rider_favor",
        "resolved_driver_favor", "resolved_partial", "dismissed",
    }
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status: {status_filter}")

    items, total = await list_disputes(db, status_filter=status_filter, limit=limit, offset=offset)
    return DisputeListResponse(disputes=[_dispute_response(d) for d in items], total=total)


@router.patch(
    "/admin/disputes/{dispute_id}/review",
    response_model=DisputeResponse,
    summary="Admin: mark a dispute as under review",
)
async def admin_review_dispute(
    dispute_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """Move an OPEN dispute to UNDER_REVIEW. Admin only."""
    try:
        dispute = await update_dispute_status(dispute_id, "under_review", db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return _dispute_response(dispute)


@router.post(
    "/admin/disputes/{dispute_id}/resolve",
    response_model=DisputeResponse,
    summary="Admin: resolve a dispute",
)
async def admin_resolve_dispute(
    dispute_id: int,
    body: DisputeResolve,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """Resolve a dispute (OPEN or UNDER_REVIEW) with outcome, notes, and optional refund. Admin only."""
    try:
        dispute = await resolve_dispute(
            dispute_id=dispute_id,
            admin_id=admin.id,
            resolution_status=body.status,
            resolution_notes=body.resolution_notes,
            refund_amount=body.refund_amount,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return _dispute_response(dispute)
