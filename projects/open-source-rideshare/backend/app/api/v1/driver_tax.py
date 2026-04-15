"""Router for driver tax reporting and 1099-NEC document management.

Driver endpoints (require DRIVER role):
  GET  /drivers/me/tax/profile              — get tax profile (tin_last4 only)
  POST /drivers/me/tax/profile/w9           — submit W-9 info
  GET  /drivers/me/tax/documents            — list all tax documents
  GET  /drivers/me/tax/documents/{year}     — get specific year's documents

Admin endpoints (require ADMIN role):
  GET  /admin/tax/documents/{year}                      — list all drivers for a year
  POST /admin/tax/generate/{year}                       — batch generate documents
  POST /admin/tax/documents/{document_id}/submit        — mark submitted to IRS
  GET  /admin/tax/profile/{driver_profile_id}           — view a driver's tax profile
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.driver_tax_document import TaxDocumentStatus
from app.models.user import User
from app.schemas.driver_tax import (
    AdminSubmitRequest,
    BatchGenerateResponse,
    TaxDocumentResponse,
    TaxProfileResponse,
    W9SubmitRequest,
)
from app.services.driver_tax import (
    admin_batch_generate,
    admin_get_tax_documents,
    generate_tax_document,
    get_driver_tax_documents,
    get_driver_tax_documents_for_year,
    get_or_create_tax_profile,
    mark_submitted,
    update_w9,
)
from sqlalchemy import select

router = APIRouter(tags=["driver-tax"])


async def _get_driver_profile_id(db: AsyncSession, user: User) -> int:
    """Resolve the authenticated driver's DriverProfile.id."""
    result = await db.execute(
        select(DriverProfile.id).where(DriverProfile.user_id == user.id)
    )
    profile_id = result.scalar_one_or_none()
    from fastapi import HTTPException
    if profile_id is None:
        raise HTTPException(status_code=404, detail="Driver profile not found.")
    return profile_id


# ---------------------------------------------------------------------------
# Driver: tax profile
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/tax/profile",
    response_model=TaxProfileResponse,
    summary="Get my tax profile (W-9 info)",
)
async def get_my_tax_profile(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> TaxProfileResponse:
    """Return the authenticated driver's tax profile.

    The full TIN is never returned — only tin_last4.
    """
    driver_profile_id = await _get_driver_profile_id(db, user)
    profile = await get_or_create_tax_profile(db, driver_profile_id)
    return TaxProfileResponse.model_validate(profile)


@router.post(
    "/drivers/me/tax/profile/w9",
    response_model=TaxProfileResponse,
    summary="Submit W-9 information",
)
async def submit_w9(
    req: W9SubmitRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> TaxProfileResponse:
    """Submit W-9 / taxpayer identification information.

    Only the last 4 digits of the TIN are accepted and stored.
    """
    driver_profile_id = await _get_driver_profile_id(db, user)
    profile = await update_w9(
        db,
        driver_profile_id=driver_profile_id,
        tin_type=req.tin_type,
        tin_last4=req.tin_last4,
        business_name=req.business_name,
    )
    return TaxProfileResponse.model_validate(profile)


# ---------------------------------------------------------------------------
# Driver: tax documents
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/tax/documents",
    response_model=list[TaxDocumentResponse],
    summary="List all my tax documents",
)
async def list_my_tax_documents(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> list[TaxDocumentResponse]:
    """Return all tax documents for the authenticated driver."""
    driver_profile_id = await _get_driver_profile_id(db, user)
    docs = await get_driver_tax_documents(db, driver_profile_id)
    return [TaxDocumentResponse.model_validate(d) for d in docs]


@router.get(
    "/drivers/me/tax/documents/{year}",
    response_model=list[TaxDocumentResponse],
    summary="Get tax documents for a specific year",
)
async def get_my_tax_documents_for_year(
    year: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> list[TaxDocumentResponse]:
    """Return tax documents for the authenticated driver for a specific tax year."""
    driver_profile_id = await _get_driver_profile_id(db, user)
    docs = await get_driver_tax_documents_for_year(db, driver_profile_id, year)
    return [TaxDocumentResponse.model_validate(d) for d in docs]


# ---------------------------------------------------------------------------
# Admin: list documents for a year
# ---------------------------------------------------------------------------


@router.get(
    "/admin/tax/documents/{year}",
    response_model=list[TaxDocumentResponse],
    summary="Admin: list all drivers' tax documents for a year",
)
async def admin_list_tax_documents(
    year: int,
    status: TaxDocumentStatus | None = Query(default=None, description="Filter by status."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[TaxDocumentResponse]:
    """Return all drivers' tax documents for the given tax year."""
    docs = await admin_get_tax_documents(db, year, status=status, limit=limit, offset=offset)
    return [TaxDocumentResponse.model_validate(d) for d in docs]


# ---------------------------------------------------------------------------
# Admin: batch generate
# ---------------------------------------------------------------------------


@router.post(
    "/admin/tax/generate/{year}",
    response_model=BatchGenerateResponse,
    status_code=200,
    summary="Admin: batch generate tax documents for all eligible drivers",
)
async def admin_batch_generate_documents(
    year: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BatchGenerateResponse:
    """Trigger batch generation of tax documents for all active drivers with earnings.

    Idempotent — re-running updates existing documents with current earnings.
    """
    result = await admin_batch_generate(db, year)
    return BatchGenerateResponse(
        tax_year=year,
        generated=result["generated"],
        skipped=result["skipped"],
        errors=result["errors"],
    )


# ---------------------------------------------------------------------------
# Admin: mark submitted
# ---------------------------------------------------------------------------


@router.post(
    "/admin/tax/documents/{document_id}/submit",
    response_model=TaxDocumentResponse,
    summary="Admin: mark a document as submitted to IRS",
)
async def admin_mark_submitted(
    document_id: int,
    req: AdminSubmitRequest | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TaxDocumentResponse:
    """Mark a tax document as submitted to the IRS."""
    notes = req.admin_notes if req else None
    doc = await mark_submitted(db, document_id, admin_notes=notes)
    return TaxDocumentResponse.model_validate(doc)


# ---------------------------------------------------------------------------
# Admin: view a driver's tax profile
# ---------------------------------------------------------------------------


@router.get(
    "/admin/tax/profile/{driver_profile_id}",
    response_model=TaxProfileResponse,
    summary="Admin: view a driver's tax profile",
)
async def admin_get_driver_tax_profile(
    driver_profile_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TaxProfileResponse:
    """Return a driver's tax profile (admin access)."""
    profile = await get_or_create_tax_profile(db, driver_profile_id)
    return TaxProfileResponse.model_validate(profile)
