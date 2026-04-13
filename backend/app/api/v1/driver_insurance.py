"""Driver insurance document management endpoints.

Driver endpoints (own documents only):
  GET  /drivers/me/insurance          — list all my documents
  POST /drivers/me/insurance          — submit new document
  PUT  /drivers/me/insurance/{doc_id} — update pending document
  GET  /drivers/me/insurance/status   — insurance status summary

Admin endpoints:
  GET /admin/insurance/documents                     — list pending_review docs
  PUT /admin/insurance/documents/{doc_id}/review     — approve or reject
  GET /admin/insurance/expiring                      — docs expiring within 30 days
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus
from app.models.user import User
from app.schemas.driver_insurance import (
    AdminReviewRequest,
    InsuranceDocumentCreate,
    InsuranceDocumentResponse,
    InsuranceDocumentUpdate,
    InsuranceStatusSummary,
)
from app.services.driver_insurance import (
    InsuranceDocumentError,
    admin_review_document,
    create_insurance_document,
    get_driver_insurance_documents,
    get_expiring_documents,
    get_insurance_status_summary,
    update_insurance_document,
)

router = APIRouter(tags=["driver-insurance"])


# ---------------------------------------------------------------------------
# Driver routes
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/insurance/status",
    response_model=InsuranceStatusSummary,
    summary="Get driver's insurance status summary",
)
async def get_my_insurance_status(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_insurance_status_summary(db, user.id)


@router.get(
    "/drivers/me/insurance",
    response_model=list[InsuranceDocumentResponse],
    summary="List all my insurance documents",
)
async def list_my_insurance_documents(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    docs = await get_driver_insurance_documents(db, user.id)
    return docs


@router.post(
    "/drivers/me/insurance",
    response_model=InsuranceDocumentResponse,
    status_code=201,
    summary="Submit a new insurance document",
)
async def submit_insurance_document(
    req: InsuranceDocumentCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    doc = await create_insurance_document(db, user.id, req)
    return doc


@router.put(
    "/drivers/me/insurance/{doc_id}",
    response_model=InsuranceDocumentResponse,
    summary="Update a pending insurance document",
)
async def update_my_insurance_document(
    doc_id: int,
    req: InsuranceDocumentUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    try:
        doc = await update_insurance_document(db, user.id, doc_id, req)
    except InsuranceDocumentError as exc:
        detail = str(exc)
        # Avoid leaking internal state — normalise to safe HTTP responses
        if "Not authorised" in detail:
            raise HTTPException(status_code=403, detail="Not authorised to edit this document")
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail="Document not found")
        raise HTTPException(status_code=409, detail=detail)
    return doc


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/insurance/documents",
    response_model=list[InsuranceDocumentResponse],
    summary="List all documents pending admin review",
)
async def admin_list_pending_documents(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverInsuranceDocument)
        .where(
            DriverInsuranceDocument.status == InsuranceDocumentStatus.PENDING_REVIEW
        )
        .order_by(DriverInsuranceDocument.created_at.asc())
    )
    return list(result.scalars().all())


@router.put(
    "/admin/insurance/documents/{doc_id}/review",
    response_model=InsuranceDocumentResponse,
    summary="Approve or reject an insurance document",
)
async def admin_review_insurance_document(
    doc_id: int,
    req: AdminReviewRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        doc = await admin_review_document(db, admin.id, doc_id, req)
    except InsuranceDocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return doc


@router.get(
    "/admin/insurance/expiring",
    response_model=list[InsuranceDocumentResponse],
    summary="List approved documents expiring within N days (default 30)",
)
async def admin_list_expiring_documents(
    days: int = Query(30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    docs = await get_expiring_documents(db, days)
    return docs
