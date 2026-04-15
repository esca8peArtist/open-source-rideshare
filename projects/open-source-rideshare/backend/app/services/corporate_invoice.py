"""Service layer for the Corporate Invoice feature.

Monthly invoices aggregate all completed, billed rides for a corporate account
within a billing period.  Admins can generate, finalize, mark as paid, void, and
regenerate (recalculate totals for draft) invoices.

Public surface
--------------
generate_invoice(db, account_id, data, requesting_user_id)
get_invoice(db, invoice_id, account_id)
list_invoices(db, account_id, *, status_filter=None)
finalize_invoice(db, invoice_id, account_id, requesting_user_id)
mark_invoice_paid(db, invoice_id, account_id, requesting_user_id, notes=None)
void_invoice(db, invoice_id, account_id, requesting_user_id)
get_invoice_line_items(db, invoice_id, account_id)
regenerate_invoice_totals(db, invoice_id, account_id, requesting_user_id)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_invoice import CorporateInvoice, InvoiceStatus
from app.models.ride import Ride


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 if the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _get_invoice(
    db: AsyncSession, invoice_id: int, account_id: int
) -> CorporateInvoice:
    """Fetch an invoice; raise 404 if not found or account mismatch."""
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


async def _build_invoice_number(
    db: AsyncSession, account_id: int, period_start
) -> str:
    """Generate a unique invoice number for the given account and period.

    Format: ``INV-{account_id:04d}-{YYYYMM}`` with a ``-N`` suffix (starting at
    ``-2``) if the base number is already taken.
    """
    base = f"INV-{account_id:04d}-{period_start.strftime('%Y%m')}"
    # Check if base exists
    result = await db.execute(
        select(CorporateInvoice).where(CorporateInvoice.invoice_number == base)
    )
    if result.scalar_one_or_none() is None:
        return base

    # Find the highest existing suffix
    suffix = 2
    while True:
        candidate = f"{base}-{suffix}"
        result = await db.execute(
            select(CorporateInvoice).where(CorporateInvoice.invoice_number == candidate)
        )
        if result.scalar_one_or_none() is None:
            return candidate
        suffix += 1


async def _aggregate_rides(
    db: AsyncSession, account_id: int, period_start, period_end
):
    """Return (total_rides, subtotal_usd) for completed account rides in the period."""
    result = await db.execute(
        select(
            func.count(Ride.id).label("total_rides"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("subtotal_usd"),
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= period_start,
            func.date(Ride.completed_at) <= period_end,
        )
    )
    row = result.one()
    total_rides = row.total_rides or 0
    subtotal_usd = Decimal(str(row.subtotal_usd or 0))
    return total_rides, subtotal_usd


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def generate_invoice(
    db: AsyncSession,
    account_id: int,
    data,
    requesting_user_id: int,
) -> CorporateInvoice:
    """Generate a new draft invoice for the account.

    Aggregates all completed rides billed to the corporate account within the
    billing period.

    Rules:
    - Requesting user must be an account admin.
    - A non-void invoice for the same account and overlapping period raises 409.
    - period_end must be >= period_start (also validated by schema).

    Raises:
        HTTPException 400: Invalid date range.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 409: A non-void invoice already exists for this period.
    """
    await _require_account_admin(db, account_id, requesting_user_id)

    if data.period_end < data.period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must be on or after period_start.",
        )

    # Check for existing non-void invoice covering the same period
    existing_result = await db.execute(
        select(CorporateInvoice).where(
            CorporateInvoice.account_id == account_id,
            CorporateInvoice.period_start == data.period_start,
            CorporateInvoice.period_end == data.period_end,
            CorporateInvoice.status != InvoiceStatus.VOID,
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A non-void invoice already exists for this billing period.",
        )

    total_rides, subtotal_usd = await _aggregate_rides(
        db, account_id, data.period_start, data.period_end
    )

    invoice_number = await _build_invoice_number(db, account_id, data.period_start)

    invoice = CorporateInvoice(
        account_id=account_id,
        invoice_number=invoice_number,
        period_start=data.period_start,
        period_end=data.period_end,
        status=InvoiceStatus.DRAFT,
        total_rides=total_rides,
        subtotal_usd=subtotal_usd,
        notes=getattr(data, "notes", None),
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def get_invoice(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
) -> CorporateInvoice:
    """Return an invoice by ID, scoped to the account.

    Raises:
        HTTPException 404: Not found or account mismatch.
    """
    return await _get_invoice(db, invoice_id, account_id)


async def list_invoices(
    db: AsyncSession,
    account_id: int,
    *,
    status_filter: InvoiceStatus | None = None,
) -> Sequence[CorporateInvoice]:
    """Return invoices for an account, ordered by period_start DESC.

    Args:
        status_filter: When provided, restricts results to that status.
    """
    q = select(CorporateInvoice).where(CorporateInvoice.account_id == account_id)
    if status_filter is not None:
        q = q.where(CorporateInvoice.status == status_filter)
    q = q.order_by(CorporateInvoice.period_start.desc())
    result = await db.execute(q)
    return result.scalars().all()


async def finalize_invoice(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    requesting_user_id: int,
) -> CorporateInvoice:
    """Transition an invoice from draft → finalized.

    Raises:
        HTTPException 400: Invoice is not in draft status.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Invoice not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    invoice = await _get_invoice(db, invoice_id, account_id)

    if invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft invoices can be finalized.",
        )

    invoice.status = InvoiceStatus.FINALIZED
    invoice.finalized_at = datetime.now(timezone.utc)
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def mark_invoice_paid(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    requesting_user_id: int,
    notes: str | None = None,
) -> CorporateInvoice:
    """Transition an invoice from finalized → paid.

    Raises:
        HTTPException 400: Invoice is not in finalized status.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Invoice not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    invoice = await _get_invoice(db, invoice_id, account_id)

    if invoice.status != InvoiceStatus.FINALIZED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only finalized invoices can be marked as paid.",
        )

    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.now(timezone.utc)
    if notes is not None:
        invoice.notes = notes
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def void_invoice(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    requesting_user_id: int,
) -> CorporateInvoice:
    """Void an invoice.

    Raises:
        HTTPException 400: Invoice is already void.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Invoice not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    invoice = await _get_invoice(db, invoice_id, account_id)

    if invoice.status == InvoiceStatus.VOID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already void.",
        )

    invoice.status = InvoiceStatus.VOID
    invoice.voided_at = datetime.now(timezone.utc)
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def get_invoice_line_items(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
) -> dict:
    """Return per-ride line items and cost-center summary for an invoice.

    No admin restriction — any account member may view line items.

    Returns:
        dict with keys: invoice_id, invoice_number, period_start, period_end,
        total_rides, subtotal_usd, line_items (list), by_cost_center (list).
    """
    invoice = await _get_invoice(db, invoice_id, account_id)

    # Fetch rides for the billing period
    rides_result = await db.execute(
        select(Ride).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date(Ride.completed_at) >= invoice.period_start,
            func.date(Ride.completed_at) <= invoice.period_end,
        ).order_by(Ride.completed_at.asc())
    )
    rides = rides_result.scalars().all()

    # Fetch cost centers for name/code lookup
    cc_ids = {r.cost_center_id for r in rides if r.cost_center_id is not None}
    cc_map: dict[int, CorporateCostCenter] = {}
    if cc_ids:
        cc_result = await db.execute(
            select(CorporateCostCenter).where(CorporateCostCenter.id.in_(cc_ids))
        )
        for cc in cc_result.scalars().all():
            cc_map[cc.id] = cc

    line_items = []
    cc_summary: dict[int | None, dict] = {}

    for ride in rides:
        fare = Decimal(str(ride.actual_fare))
        cc = cc_map.get(ride.cost_center_id) if ride.cost_center_id else None
        line_items.append(
            {
                "ride_id": ride.id,
                "completed_at": ride.completed_at,
                "actual_fare": fare,
                "cost_center_id": ride.cost_center_id,
                "cost_center_name": cc.name if cc else None,
                "cost_center_code": cc.code if cc else None,
            }
        )

        key = ride.cost_center_id
        if key not in cc_summary:
            cc_summary[key] = {
                "cost_center_name": cc.name if cc else None,
                "cost_center_code": cc.code if cc else None,
                "ride_count": 0,
                "subtotal": Decimal("0.00"),
            }
        cc_summary[key]["ride_count"] += 1
        cc_summary[key]["subtotal"] += fare

    by_cost_center = sorted(
        cc_summary.values(),
        key=lambda x: x["subtotal"],
        reverse=True,
    )

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "total_rides": invoice.total_rides,
        "subtotal_usd": invoice.subtotal_usd,
        "line_items": line_items,
        "by_cost_center": by_cost_center,
    }


async def regenerate_invoice_totals(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    requesting_user_id: int,
) -> CorporateInvoice:
    """Re-aggregate ride totals for a draft invoice.

    Useful when rides have been added/corrected after initial generation.

    Raises:
        HTTPException 400: Invoice is not in draft status.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Invoice not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    invoice = await _get_invoice(db, invoice_id, account_id)

    if invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft invoices can have totals regenerated.",
        )

    total_rides, subtotal_usd = await _aggregate_rides(
        db, account_id, invoice.period_start, invoice.period_end
    )

    invoice.total_rides = total_rides
    invoice.subtotal_usd = subtotal_usd
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice
