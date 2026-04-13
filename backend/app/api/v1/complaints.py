"""Complaint and dispute management API endpoints.

User endpoints (auth required, own complaints only):
  POST /complaints                     — file a new complaint
  GET  /complaints/me/filed            — complaints I have filed
  GET  /complaints/me/received         — complaints filed against me

Admin endpoints (admin auth required):
  GET  /admin/complaints               — list all complaints, ?status= filter
  GET  /admin/complaints/{id}          — get single complaint with user names
  PUT  /admin/complaints/{id}          — update status and admin notes
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.complaint import ComplaintStatus
from app.models.user import User
from app.schemas.complaint import (
    AdminComplaintResponse,
    ComplaintCreate,
    ComplaintResponse,
    ComplaintUpdateAdmin,
)
from app.services.complaints import (
    ComplaintError,
    admin_get_complaint,
    admin_list_complaints,
    admin_update_complaint,
    file_complaint,
    get_complaints_against_me,
    get_my_complaints,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["complaints"])


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/complaints",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_complaint(
    req: ComplaintCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """File a formal complaint against another user.

    The complaint is created with PENDING status and enters the admin review queue.
    Providing ride_id is strongly recommended — the API will verify that both
    parties participated in that ride.
    """
    try:
        complaint = await file_complaint(db, filed_by_user_id=user.id, data=req)
    except ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(complaint)
    return complaint


@router.get("/complaints/me/filed", response_model=list[ComplaintResponse])
async def list_my_filed_complaints(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List complaints filed by the authenticated user, newest first."""
    return await get_my_complaints(db, user_id=user.id, skip=skip, limit=limit)


@router.get("/complaints/me/received", response_model=list[ComplaintResponse])
async def list_complaints_against_me(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List complaints filed against the authenticated user, newest first.

    admin_notes are hidden while the complaint is still pending or under review,
    and are only disclosed once the complaint reaches a resolved or dismissed state.
    """
    return await get_complaints_against_me(db, user_id=user.id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/complaints", response_model=list[AdminComplaintResponse])
async def admin_list_all_complaints(
    status_filter: ComplaintStatus | None = Query(
        None, alias="status", description="Filter by status"
    ),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all complaints with optional status filter, newest first."""
    complaints = await admin_list_complaints(db, status=status_filter, skip=skip, limit=limit)
    return [_to_admin_response(c) for c in complaints]


@router.get("/admin/complaints/{complaint_id}", response_model=AdminComplaintResponse)
async def admin_get_single_complaint(
    complaint_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: get full details for a specific complaint."""
    try:
        complaint = await admin_get_complaint(db, complaint_id)
    except ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return _to_admin_response(complaint)


@router.put("/admin/complaints/{complaint_id}", response_model=AdminComplaintResponse)
async def admin_update_single_complaint(
    complaint_id: int,
    req: ComplaintUpdateAdmin,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update a complaint's status and notes.

    Valid transitions from PENDING or REVIEWING:
      - reviewing  — begin investigation (no notes required)
      - resolved   — close with outcome (admin notes recommended)
      - dismissed  — reject as unfounded (admin notes recommended)

    Once resolved or dismissed, no further updates are permitted.
    """
    try:
        complaint = await admin_update_complaint(
            db, complaint_id=complaint_id, admin_id=admin.id, data=req
        )
    except ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(complaint)
    return _to_admin_response(complaint)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_admin_response(complaint) -> AdminComplaintResponse:
    """Build an AdminComplaintResponse from a Complaint ORM object.

    Attempts to read user names from eagerly-loaded relationships. Falls back
    to placeholder strings if relationships were not loaded (e.g., in unit
    tests using mock objects).
    """
    try:
        filed_by_name = complaint.filed_by.name if complaint.filed_by else "Unknown"
    except Exception:
        filed_by_name = "Unknown"

    try:
        against_name = complaint.against.name if complaint.against else "Unknown"
    except Exception:
        against_name = "Unknown"

    return AdminComplaintResponse(
        id=complaint.id,
        filed_by_user_id=complaint.filed_by_user_id,
        against_user_id=complaint.against_user_id,
        ride_id=complaint.ride_id,
        category=complaint.category,
        description=complaint.description,
        status=complaint.status,
        admin_notes=complaint.admin_notes,
        created_at=complaint.created_at,
        updated_at=complaint.updated_at,
        filed_by_name=filed_by_name,
        against_name=against_name,
        resolved_by_admin_id=complaint.resolved_by_admin_id,
    )
