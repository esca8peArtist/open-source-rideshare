"""Service layer for corporate invoice due date and overdue tracking.

Public surface
--------------
set_invoice_due_date(db, invoice_id, account_id, req)
get_overdue_invoices(db, account_id=None, as_of=None)
run_overdue_scan(db, as_of=None)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_invoice import CorporateInvoice, InvoiceStatus
from app.schemas.corporate_invoice_due_date import (
    InvoiceOverdueScanResponse,
    OverdueInvoiceRow,
    SetInvoiceDueDateRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_invoice_for_account(
    db: AsyncSession, invoice_id: int, account_id: int
) -> CorporateInvoice:
    """Fetch an invoice scoped to an account; raise 404 if not found."""
    result = await db.execute(
        select(CorporateInvoice).where(
            CorporateInvoice.id == invoice_id,
            CorporateInvoice.account_id == account_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )
    return invoice


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def set_invoice_due_date(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    req: SetInvoiceDueDateRequest,
) -> CorporateInvoice:
    """Set or clear the due_date and payment_terms_days on an invoice.

    The invoice must belong to account_id and must not be PAID or VOID.

    Raises:
        HTTPException 400: Invoice is PAID or VOID.
        HTTPException 404: Invoice not found or account mismatch.
    """
    invoice = await _get_invoice_for_account(db, invoice_id, account_id)

    if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.VOID):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot set due date on a PAID or VOID invoice.",
        )

    invoice.payment_terms_days = req.payment_terms_days
    invoice.due_date = req.due_date

    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def get_overdue_invoices(
    db: AsyncSession,
    account_id: int | None = None,
    as_of: date | None = None,
) -> list[OverdueInvoiceRow]:
    """Return FINALIZED invoices whose due_date is before as_of and status is not PAID/VOID.

    Args:
        account_id: When provided, restrict results to that account.
        as_of: Reference date for overdue calculation (defaults to today).

    Returns:
        List of OverdueInvoiceRow sorted by due_date ascending (oldest first).
    """
    if as_of is None:
        as_of = date.today()

    q = select(CorporateInvoice).where(
        CorporateInvoice.due_date.is_not(None),
        CorporateInvoice.due_date < as_of,
        CorporateInvoice.status == InvoiceStatus.FINALIZED,
    )
    if account_id is not None:
        q = q.where(CorporateInvoice.account_id == account_id)

    q = q.order_by(CorporateInvoice.due_date.asc())

    result = await db.execute(q)
    invoices = result.scalars().all()

    rows: list[OverdueInvoiceRow] = []
    for inv in invoices:
        days_overdue = (as_of - inv.due_date).days
        rows.append(
            OverdueInvoiceRow(
                invoice_id=inv.id,
                account_id=inv.account_id,
                invoice_number=inv.invoice_number,
                due_date=inv.due_date,
                days_overdue=days_overdue,
                subtotal_usd=inv.subtotal_usd,
                status=inv.status,
            )
        )
    return rows


async def run_overdue_scan(
    db: AsyncSession,
    as_of: date | None = None,
) -> InvoiceOverdueScanResponse:
    """Scan all FINALIZED invoices that have a due_date set.

    For each overdue invoice (due_date < as_of) that has no prior overdue note,
    appends an overdue notice to the invoice notes field.

    Returns:
        InvoiceOverdueScanResponse with counts.
    """
    if as_of is None:
        as_of = date.today()

    # Fetch all FINALIZED invoices that have a due_date
    result = await db.execute(
        select(CorporateInvoice).where(
            CorporateInvoice.due_date.is_not(None),
            CorporateInvoice.status == InvoiceStatus.FINALIZED,
        )
    )
    all_invoices: Sequence[CorporateInvoice] = result.scalars().all()

    scanned = len(all_invoices)
    overdue_count = 0
    newly_flagged = 0

    overdue_marker = "[OVERDUE]"

    for inv in all_invoices:
        if inv.due_date < as_of:
            overdue_count += 1
            existing_notes = inv.notes or ""
            if overdue_marker not in existing_notes:
                # Append overdue marker without clobbering existing notes
                inv.notes = (
                    f"{existing_notes.strip()} {overdue_marker}".strip()
                    if existing_notes.strip()
                    else overdue_marker
                )
                db.add(inv)
                newly_flagged += 1

    await db.commit()

    return InvoiceOverdueScanResponse(
        scanned=scanned,
        overdue_count=overdue_count,
        newly_flagged=newly_flagged,
        as_of=as_of,
    )
