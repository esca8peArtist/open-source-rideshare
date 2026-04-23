"""Driver document expiry endpoints.

GET /drivers/me/document-expiry  — driver sees their own expiring/expired docs
GET /admin/document-expiry       — admin fleet view of all drivers with expiring docs
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_driver
from app.models.user import User
from app.schemas.driver_document_expiry import (
    AdminDocumentExpiryItem,
    AdminDocumentExpiryResponse,
    DocumentExpiryItem,
    DriverDocumentExpiryResponse,
)
from app.services.driver_document_expiry import (
    get_expiring_documents,
    get_expiring_documents_for_driver,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-document-expiry"])


def _urgency(days_remaining: int) -> str:
    if days_remaining < 0:
        return "expired"
    if days_remaining <= 7:
        return "critical"
    if days_remaining <= 30:
        return "warning"
    return "ok"


@router.get(
    "/drivers/me/document-expiry",
    response_model=DriverDocumentExpiryResponse,
    summary="Get my document expiry status",
    description=(
        "Returns all approved documents expiring within the look-ahead window "
        "(default 60 days), including already-expired ones. "
        "Only the authenticated driver's own documents are returned."
    ),
)
async def get_my_document_expiry(
    days_ahead: int = Query(
        60,
        ge=0,
        le=365,
        description="Look-ahead window in days (0 = only expired docs).",
    ),
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverDocumentExpiryResponse:
    docs = await get_expiring_documents_for_driver(
        db=db, driver_id=current_user.id, days_ahead=days_ahead
    )
    items = [
        DocumentExpiryItem(
            document_type=d.document_type,
            expiry_date=d.expiry_date,
            days_remaining=d.days_remaining,
            is_expired=d.days_remaining < 0,
            urgency=_urgency(d.days_remaining),
        )
        for d in docs
    ]
    return DriverDocumentExpiryResponse(
        driver_user_id=current_user.id,
        documents=items,
        has_expired=any(i.is_expired for i in items),
        has_warning=len(items) > 0,
    )


@router.get(
    "/admin/document-expiry",
    response_model=AdminDocumentExpiryResponse,
    summary="Admin: fleet document expiry overview",
    description=(
        "Returns all approved driver documents expiring within *days_ahead* days "
        "(default 30), including already-expired ones. "
        "Use ``expired_only=true`` to restrict to documents already past their expiry date."
    ),
)
async def admin_get_document_expiry(
    days_ahead: int = Query(
        30,
        ge=0,
        le=365,
        description="Look-ahead window in days.",
    ),
    expired_only: bool = Query(
        False,
        description="When true, return only documents that are already expired.",
    ),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDocumentExpiryResponse:
    docs = await get_expiring_documents(db=db, days_ahead=days_ahead)
    if expired_only:
        docs = [d for d in docs if d.days_remaining < 0]
    items = [
        AdminDocumentExpiryItem(
            driver_user_id=d.driver_id,
            document_type=d.document_type,
            expiry_date=d.expiry_date,
            days_remaining=d.days_remaining,
        )
        for d in docs
    ]
    return AdminDocumentExpiryResponse(
        days_ahead=days_ahead,
        total=len(items),
        items=items,
    )
