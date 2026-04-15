"""Corporate Invoice API endpoints.

Member endpoints (require active corporate account membership):
  POST   /corporate/accounts/me/invoices                     — generate (admin, 201)
  GET    /corporate/accounts/me/invoices                     — list (any member, 200)
  GET    /corporate/accounts/me/invoices/{id}                — get (any member, 200)
  GET    /corporate/accounts/me/invoices/{id}/line-items     — line items (any member, 200)
  PUT    /corporate/accounts/me/invoices/{id}/finalize       — finalize (admin, 200)
  PUT    /corporate/accounts/me/invoices/{id}/paid           — mark paid (admin, 200)
  DELETE /corporate/accounts/me/invoices/{id}                — void (admin, 204)
  POST   /corporate/accounts/me/invoices/{id}/regenerate     — recalculate totals (admin, 200)

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/invoices                        — list
  GET    /admin/corporate/accounts/{account_id}/invoices/{id}                   — get
  GET    /admin/corporate/accounts/{account_id}/invoices/{id}/line-items        — line items
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.corporate_invoice import InvoiceStatus
from app.models.user import User
from app.schemas.corporate_invoice import (
    CorporateInvoiceCreate,
    CorporateInvoiceResponse,
    InvoiceMarkPaidRequest,
)
from app.services.corporate_invoice import (
    finalize_invoice,
    generate_invoice,
    get_invoice,
    get_invoice_line_items,
    list_invoices,
    mark_invoice_paid,
    regenerate_invoice_totals,
    void_invoice,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-invoices"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID the user belongs to.

    Raises HTTP 404 if the user is not an active member of any account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return membership.account_id


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/invoices",
    response_model=CorporateInvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a monthly invoice for your corporate account",
)
async def generate_my_invoice(
    data: CorporateInvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a draft invoice for the caller's corporate account.

    Aggregates all completed rides billed to the account within the billing
    period.  Only account admins may generate invoices.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await generate_invoice(
        db, account_id, data, requesting_user_id=current_user.id
    )


@router.get(
    "/corporate/accounts/me/invoices",
    response_model=list[CorporateInvoiceResponse],
    summary="List invoices for your corporate account",
)
async def list_my_invoices(
    status_filter: InvoiceStatus | None = Query(
        None, description="Filter by invoice status."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all invoices for the caller's corporate account, ordered by period_start DESC."""
    account_id = await _get_member_account_id(db, current_user.id)
    return await list_invoices(db, account_id, status_filter=status_filter)


@router.get(
    "/corporate/accounts/me/invoices/{invoice_id}",
    response_model=CorporateInvoiceResponse,
    summary="Get a specific invoice",
)
async def get_my_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single invoice by ID, scoped to the caller's account."""
    account_id = await _get_member_account_id(db, current_user.id)
    return await get_invoice(db, invoice_id, account_id)


@router.get(
    "/corporate/accounts/me/invoices/{invoice_id}/line-items",
    summary="Get ride line items for an invoice",
)
async def get_my_invoice_line_items(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return per-ride line items and cost-center breakdown for an invoice.

    Any active account member may view line items.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await get_invoice_line_items(db, invoice_id, account_id)


@router.put(
    "/corporate/accounts/me/invoices/{invoice_id}/finalize",
    response_model=CorporateInvoiceResponse,
    summary="Finalize a draft invoice",
)
async def finalize_my_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Transition a draft invoice to finalized status.

    Only account admins may finalize invoices.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await finalize_invoice(
        db, invoice_id, account_id, requesting_user_id=current_user.id
    )


@router.put(
    "/corporate/accounts/me/invoices/{invoice_id}/paid",
    response_model=CorporateInvoiceResponse,
    summary="Mark a finalized invoice as paid",
)
async def mark_my_invoice_paid(
    invoice_id: int,
    data: InvoiceMarkPaidRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Transition a finalized invoice to paid status.

    Only account admins may mark invoices as paid.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    notes = data.notes if data else None
    return await mark_invoice_paid(
        db, invoice_id, account_id, requesting_user_id=current_user.id, notes=notes
    )


@router.delete(
    "/corporate/accounts/me/invoices/{invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Void an invoice",
)
async def void_my_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Void an invoice.  Any non-void invoice can be voided.

    Only account admins may void invoices.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    await void_invoice(
        db, invoice_id, account_id, requesting_user_id=current_user.id
    )


@router.post(
    "/corporate/accounts/me/invoices/{invoice_id}/regenerate",
    response_model=CorporateInvoiceResponse,
    summary="Recalculate totals for a draft invoice",
)
async def regenerate_my_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-aggregate ride totals for a draft invoice.

    Useful when rides have been corrected after initial generation.
    Only account admins may regenerate invoice totals.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await regenerate_invoice_totals(
        db, invoice_id, account_id, requesting_user_id=current_user.id
    )


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/invoices",
    response_model=list[CorporateInvoiceResponse],
    summary="[Admin] List invoices for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_invoices(
    account_id: int,
    status_filter: InvoiceStatus | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List invoices for any corporate account (platform admin only)."""
    return await list_invoices(db, account_id, status_filter=status_filter)


@router.get(
    "/admin/corporate/accounts/{account_id}/invoices/{invoice_id}",
    response_model=CorporateInvoiceResponse,
    summary="[Admin] Get a specific invoice for any account",
    dependencies=[Depends(require_admin)],
)
async def admin_get_invoice(
    account_id: int,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single invoice for any corporate account (platform admin only)."""
    return await get_invoice(db, invoice_id, account_id)


@router.get(
    "/admin/corporate/accounts/{account_id}/invoices/{invoice_id}/line-items",
    summary="[Admin] Get ride line items for any account's invoice",
    dependencies=[Depends(require_admin)],
)
async def admin_get_invoice_line_items(
    account_id: int,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return line items for any account's invoice (platform admin only)."""
    return await get_invoice_line_items(db, invoice_id, account_id)
