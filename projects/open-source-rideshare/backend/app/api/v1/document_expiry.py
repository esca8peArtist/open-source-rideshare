"""Driver document expiry alert endpoints.

Driver endpoints:
  GET /drivers/me/documents/expiry-status
      Returns expiring/expired documents for the authenticated driver.
      Optional query param: days (default 30) — lookahead window.

Admin endpoints:
  GET  /admin/documents/expiring
      Paginated list of all drivers with documents expiring within `days`.
      Optional filter: doc_type (license | registration | insurance | inspection).

  POST /admin/documents/expiry/scan
      Bulk-marks active documents past their expiry date as EXPIRED.
      Idempotent — safe to call on a schedule.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.document_expiry import (
    AdminExpiringDocumentsResponse,
    AdminExpiringDocumentRow,
    DriverExpiryStatusResponse,
    ExpiringDocumentItem,
    ExpiryScaResponse,
)
from app.services.document_expiry_alerts import (
    get_all_expiring_documents,
    get_driver_expiry_status,
    run_expiry_scan,
)

router = APIRouter(tags=["document-expiry"])

DocType = Literal["license", "registration", "insurance", "inspection"]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

@router.get(
    "/drivers/me/documents/expiry-status",
    response_model=DriverExpiryStatusResponse,
    summary="Get document expiry status for the authenticated driver",
)
async def driver_expiry_status(
    days: int = Query(30, ge=1, le=365, description="Look-ahead window in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverExpiryStatusResponse:
    """Return all documents that are expiring soon or already expired.

    A document is included if its expiry date falls within the next `days`
    days, or is already in the past.
    """
    status = await get_driver_expiry_status(user.id, db, days_ahead=days)
    return DriverExpiryStatusResponse(
        driver_id=status.driver_id,
        expiring=[
            ExpiringDocumentItem(
                doc_type=d.doc_type,
                doc_id=d.doc_id,
                expiry_date=d.expiry_date,
                days_until_expiry=d.days_until_expiry,
                status=d.status,
            )
            for d in status.expiring
        ],
        expired=[
            ExpiringDocumentItem(
                doc_type=d.doc_type,
                doc_id=d.doc_id,
                expiry_date=d.expiry_date,
                days_until_expiry=d.days_until_expiry,
                status=d.status,
            )
            for d in status.expired
        ],
        has_issues=status.has_issues,
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@router.get(
    "/admin/documents/expiring",
    response_model=AdminExpiringDocumentsResponse,
    summary="List all drivers with documents expiring soon (admin)",
)
async def admin_expiring_documents(
    days: int = Query(30, ge=1, le=365, description="Look-ahead window in days"),
    doc_type: DocType | None = Query(None, description="Filter to one document type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminExpiringDocumentsResponse:
    """Return all driver documents expiring within the look-ahead window.

    Results are sorted: already-expired first, then soonest expiry.
    """
    rows = await get_all_expiring_documents(
        db, days_ahead=days, doc_type=doc_type, skip=skip, limit=limit
    )
    return AdminExpiringDocumentsResponse(
        items=[
            AdminExpiringDocumentRow(
                driver_id=r.driver_id,
                doc_type=r.doc_type,
                doc_id=r.doc_id,
                expiry_date=r.expiry_date,
                days_until_expiry=r.days_until_expiry,
                status=r.status,
            )
            for r in rows
        ],
        total=len(rows),
        days_ahead=days,
        doc_type_filter=doc_type,
    )


@router.post(
    "/admin/documents/expiry/scan",
    response_model=ExpiryScaResponse,
    summary="Bulk-mark overdue documents as EXPIRED (admin)",
)
async def admin_run_expiry_scan(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ExpiryScaResponse:
    """Mark all active documents whose expiry date has passed as EXPIRED.

    Idempotent — safe to call on a scheduler (e.g. nightly cron).
    Returns counts of documents updated per type.
    """
    result = await run_expiry_scan(db)
    return ExpiryScaResponse(
        licenses_marked_expired=result.licenses_marked_expired,
        registrations_marked_expired=result.registrations_marked_expired,
        insurance_marked_expired=result.insurance_marked_expired,
        inspections_marked_expired=result.inspections_marked_expired,
        total_marked_expired=result.total_marked_expired,
    )
