"""Corporate Invoice Due Date API endpoints.

Member endpoints (require active corporate account membership):
  PUT  /corporate/accounts/me/invoices/{invoice_id}/due-date
       — Set due date for own account invoice (account admin)
  GET  /corporate/accounts/me/invoices/overdue
       — List overdue invoices for own account (any member)

Platform-admin endpoints:
  GET  /admin/corporate/invoices/overdue
       — List all overdue invoices, optionally filtered by ?account_id=
  POST /admin/corporate/invoices/overdue-scan
       — Run a full platform-wide overdue scan
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.corporate_invoice import CorporateInvoice
from app.models.user import User
from app.schemas.corporate_invoice import CorporateInvoiceResponse
from app.schemas.corporate_invoice_due_date import (
    InvoiceOverdueScanResponse,
    OverdueInvoicesResponse,
    SetInvoiceDueDateRequest,
)
from app.services.corporate_invoice_due_date import (
    get_overdue_invoices,
    run_overdue_scan,
    set_invoice_due_date,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-invoice-due-date"])


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


@router.put(
    "/corporate/accounts/me/invoices/{invoice_id}/due-date",
    response_model=CorporateInvoiceResponse,
    summary="Set due date for an invoice on your corporate account",
)
async def set_my_invoice_due_date(
    invoice_id: int,
    data: SetInvoiceDueDateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set or clear the due_date and payment_terms_days on an invoice.

    The invoice must belong to the caller's corporate account and must not
    be in PAID or VOID status.  Only account admins may set due dates.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await set_invoice_due_date(db, invoice_id, account_id, data)


@router.get(
    "/corporate/accounts/me/invoices/overdue",
    response_model=OverdueInvoicesResponse,
    summary="List overdue invoices for your corporate account",
)
async def list_my_overdue_invoices(
    as_of: date | None = Query(
        None,
        description="Reference date for overdue calculation (defaults to today).",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return FINALIZED invoices whose due_date has passed, scoped to the caller's account.

    Any active account member may call this endpoint.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    rows = await get_overdue_invoices(db, account_id=account_id, as_of=as_of)
    return OverdueInvoicesResponse(invoices=rows, total=len(rows))


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/invoices/overdue",
    response_model=OverdueInvoicesResponse,
    summary="[Admin] List all overdue invoices across all accounts",
    dependencies=[Depends(require_admin)],
)
async def admin_list_overdue_invoices(
    account_id: int | None = Query(
        None,
        description="Restrict results to a specific corporate account.",
    ),
    as_of: date | None = Query(
        None,
        description="Reference date for overdue calculation (defaults to today).",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return all overdue FINALIZED invoices platform-wide (platform admin only).

    Optionally filter by account_id or supply a custom as_of date.
    """
    rows = await get_overdue_invoices(db, account_id=account_id, as_of=as_of)
    return OverdueInvoicesResponse(invoices=rows, total=len(rows))


@router.post(
    "/admin/corporate/invoices/overdue-scan",
    response_model=InvoiceOverdueScanResponse,
    summary="[Admin] Run a full overdue invoice scan",
    dependencies=[Depends(require_admin)],
)
async def admin_overdue_scan(
    as_of: date | None = Query(
        None,
        description="Reference date for overdue calculation (defaults to today).",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Scan all FINALIZED invoices with a due_date and flag overdue ones.

    Appends an [OVERDUE] marker to invoice notes for newly detected overdue
    invoices that have not been flagged before.  Returns a summary.
    """
    return await run_overdue_scan(db, as_of=as_of)
