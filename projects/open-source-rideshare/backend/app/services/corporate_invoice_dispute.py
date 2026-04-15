"""Service layer for Corporate Invoice Disputes.

Corporate account members can formally dispute charges on their invoices.
Platform admins review and resolve disputes.  Every dispute event is
persisted for audit and compliance purposes.

Public surface
--------------
submit_dispute(db, invoice_id, account_id, submitted_by_id, dispute_type, description,
               disputed_rides, disputed_amount_usd) -> InvoiceDisputeResponse
get_dispute(db, dispute_id) -> CorporateInvoiceDispute | None
get_dispute_by_invoice(db, invoice_id, account_id) -> list[CorporateInvoiceDispute]
list_account_disputes(db, account_id, status_filter, skip, limit) -> list[CorporateInvoiceDispute]
update_dispute(db, dispute_id, account_id, **fields) -> InvoiceDisputeResponse
mark_under_review(db, dispute_id, reviewed_by_id) -> InvoiceDisputeResponse
resolve_dispute(db, dispute_id, resolved_by_id, resolution, resolution_note) -> InvoiceDisputeResponse
withdraw_dispute(db, dispute_id, account_id) -> InvoiceDisputeResponse
list_all_disputes(db, status_filter, skip, limit) -> list[CorporateInvoiceDispute]
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_invoice import CorporateInvoice
from app.models.corporate_invoice_dispute import (
    CorporateInvoiceDispute,
    DisputeStatus,
    DisputeType,
)
from app.schemas.corporate_invoice_dispute import InvoiceDisputeResponse


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = {DisputeStatus.submitted, DisputeStatus.under_review}
_RESOLVED_STATUSES = {
    DisputeStatus.resolved_upheld,
    DisputeStatus.resolved_denied,
    DisputeStatus.withdrawn,
}


def _to_response(dispute: CorporateInvoiceDispute) -> InvoiceDisputeResponse:
    """Convert a model instance to an InvoiceDisputeResponse schema object."""
    return InvoiceDisputeResponse(
        id=dispute.id,
        invoice_id=dispute.invoice_id,
        account_id=dispute.account_id,
        submitted_by_id=dispute.submitted_by_id,
        dispute_type=dispute.dispute_type,
        description=dispute.description,
        disputed_rides=dispute.disputed_rides,
        disputed_amount_usd=dispute.disputed_amount_usd,
        status=dispute.status,
        resolution_note=dispute.resolution_note,
        resolved_by_id=dispute.resolved_by_id,
        resolved_at=dispute.resolved_at,
        created_at=dispute.created_at,
        updated_at=dispute.updated_at,
    )


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


async def submit_dispute(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    submitted_by_id: Optional[int],
    dispute_type: DisputeType,
    description: str,
    disputed_rides: Optional[list],
    disputed_amount_usd: Optional[Decimal],
) -> InvoiceDisputeResponse:
    """Submit a new dispute against a corporate invoice.

    Validates that the invoice exists and belongs to the account, and that
    there is no currently active dispute for the invoice.

    Args:
        db:                  Async database session.
        invoice_id:          Invoice being disputed.
        account_id:          Corporate account submitting the dispute.
        submitted_by_id:     ID of the member submitting the dispute.
        dispute_type:        Structured dispute category.
        description:         Required free-text explanation.
        disputed_rides:      Optional list of specific ride IDs being disputed.
        disputed_amount_usd: Optional specific amount being disputed.

    Returns:
        InvoiceDisputeResponse for the newly created dispute.

    Raises:
        HTTP 404: When the invoice does not exist or does not belong to the account.
        HTTP 409: When the invoice already has an active dispute.
    """
    # Verify invoice exists and belongs to account
    invoice_result = await db.execute(
        select(CorporateInvoice).where(
            CorporateInvoice.id == invoice_id,
            CorporateInvoice.account_id == account_id,
        )
    )
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found or does not belong to this account.",
        )

    # Check for existing active dispute
    active_result = await db.execute(
        select(CorporateInvoiceDispute).where(
            CorporateInvoiceDispute.invoice_id == invoice_id,
            CorporateInvoiceDispute.status.in_(list(_ACTIVE_STATUSES)),
        )
    )
    if active_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invoice already has an active dispute.",
        )

    dispute = CorporateInvoiceDispute(
        invoice_id=invoice_id,
        account_id=account_id,
        submitted_by_id=submitted_by_id,
        dispute_type=dispute_type,
        description=description,
        disputed_rides=disputed_rides,
        disputed_amount_usd=disputed_amount_usd,
        status=DisputeStatus.submitted,
    )
    db.add(dispute)
    await db.commit()
    await db.refresh(dispute)
    return _to_response(dispute)


async def get_dispute(
    db: AsyncSession,
    dispute_id: int,
) -> CorporateInvoiceDispute | None:
    """Return a single dispute by ID, or None if not found.

    Args:
        db:         Async database session.
        dispute_id: Dispute primary key.

    Returns:
        CorporateInvoiceDispute or None.
    """
    result = await db.execute(
        select(CorporateInvoiceDispute).where(
            CorporateInvoiceDispute.id == dispute_id
        )
    )
    return result.scalar_one_or_none()


async def get_dispute_by_invoice(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
) -> Sequence[CorporateInvoiceDispute]:
    """Return all disputes for a specific invoice, ordered newest first.

    Args:
        db:         Async database session.
        invoice_id: Invoice to look up disputes for.
        account_id: Account that owns the invoice (for access control).

    Returns:
        List of CorporateInvoiceDispute instances ordered by created_at desc.
    """
    result = await db.execute(
        select(CorporateInvoiceDispute)
        .where(
            CorporateInvoiceDispute.invoice_id == invoice_id,
            CorporateInvoiceDispute.account_id == account_id,
        )
        .order_by(CorporateInvoiceDispute.created_at.desc())
    )
    return result.scalars().all()


async def list_account_disputes(
    db: AsyncSession,
    account_id: int,
    status_filter: Optional[DisputeStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[CorporateInvoiceDispute]:
    """List all disputes for a corporate account, with optional status filter.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        status_filter: Optional status to filter by.
        skip:          Pagination offset.
        limit:         Maximum records to return.

    Returns:
        List of CorporateInvoiceDispute instances ordered by created_at desc.
    """
    query = select(CorporateInvoiceDispute).where(
        CorporateInvoiceDispute.account_id == account_id
    )
    if status_filter is not None:
        query = query.where(CorporateInvoiceDispute.status == status_filter)
    query = query.order_by(CorporateInvoiceDispute.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


async def update_dispute(
    db: AsyncSession,
    dispute_id: int,
    account_id: int,
    **fields,
) -> InvoiceDisputeResponse:
    """Update a pending dispute's fields.

    Only disputes in 'submitted' status may be edited.

    Args:
        db:         Async database session.
        dispute_id: Dispute to update.
        account_id: Account that owns the dispute (for access control).
        **fields:   Field name/value pairs to update.

    Returns:
        Updated InvoiceDisputeResponse.

    Raises:
        HTTP 404: When dispute not found or belongs to a different account.
        HTTP 409: When dispute is not in 'submitted' status.
    """
    dispute = await get_dispute(db, dispute_id)
    if dispute is None or dispute.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )

    if dispute.status != DisputeStatus.submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dispute can only be edited while in 'submitted' status.",
        )

    for key, value in fields.items():
        if value is not None:
            setattr(dispute, key, value)

    await db.commit()
    await db.refresh(dispute)
    return _to_response(dispute)


async def mark_under_review(
    db: AsyncSession,
    dispute_id: int,
    reviewed_by_id: Optional[int],
) -> InvoiceDisputeResponse:
    """Mark a dispute as under review (platform-admin action).

    Args:
        db:             Async database session.
        dispute_id:     Dispute to mark as under review.
        reviewed_by_id: ID of the admin performing the action.

    Returns:
        Updated InvoiceDisputeResponse.

    Raises:
        HTTP 404: When dispute not found.
        HTTP 409: When dispute is already resolved or withdrawn.
    """
    dispute = await get_dispute(db, dispute_id)
    if dispute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )

    if dispute.status in _RESOLVED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dispute has already been resolved or withdrawn.",
        )

    dispute.status = DisputeStatus.under_review
    await db.commit()
    await db.refresh(dispute)
    return _to_response(dispute)


async def resolve_dispute(
    db: AsyncSession,
    dispute_id: int,
    resolved_by_id: Optional[int],
    resolution: DisputeStatus,
    resolution_note: Optional[str],
) -> InvoiceDisputeResponse:
    """Resolve a dispute as upheld or denied (platform-admin action).

    Args:
        db:              Async database session.
        dispute_id:      Dispute to resolve.
        resolved_by_id:  ID of the admin resolving the dispute.
        resolution:      Final status — resolved_upheld or resolved_denied.
        resolution_note: Optional admin note explaining the decision.

    Returns:
        Updated InvoiceDisputeResponse.

    Raises:
        HTTP 404: When dispute not found.
        HTTP 409: When dispute is already resolved or withdrawn.
    """
    dispute = await get_dispute(db, dispute_id)
    if dispute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )

    if dispute.status in _RESOLVED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dispute has already been resolved or withdrawn.",
        )

    dispute.status = resolution
    dispute.resolved_by_id = resolved_by_id
    dispute.resolved_at = datetime.now(timezone.utc)
    dispute.resolution_note = resolution_note

    await db.commit()
    await db.refresh(dispute)
    return _to_response(dispute)


async def withdraw_dispute(
    db: AsyncSession,
    dispute_id: int,
    account_id: int,
) -> InvoiceDisputeResponse:
    """Withdraw a dispute before it is resolved (member action).

    Args:
        db:         Async database session.
        dispute_id: Dispute to withdraw.
        account_id: Account that owns the dispute (for access control).

    Returns:
        Updated InvoiceDisputeResponse.

    Raises:
        HTTP 404: When dispute not found or belongs to a different account.
        HTTP 409: When dispute has already been resolved.
    """
    dispute = await get_dispute(db, dispute_id)
    if dispute is None or dispute.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )

    if dispute.status in {DisputeStatus.resolved_upheld, DisputeStatus.resolved_denied}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot withdraw a dispute that has already been resolved.",
        )

    if dispute.status == DisputeStatus.withdrawn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dispute has already been withdrawn.",
        )

    dispute.status = DisputeStatus.withdrawn
    await db.commit()
    await db.refresh(dispute)
    return _to_response(dispute)


async def list_all_disputes(
    db: AsyncSession,
    status_filter: Optional[DisputeStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[CorporateInvoiceDispute]:
    """List all disputes across all accounts (platform-admin action).

    Args:
        db:            Async database session.
        status_filter: Optional status to filter by.
        skip:          Pagination offset.
        limit:         Maximum records to return.

    Returns:
        List of CorporateInvoiceDispute instances ordered by created_at desc.
    """
    query = select(CorporateInvoiceDispute)
    if status_filter is not None:
        query = query.where(CorporateInvoiceDispute.status == status_filter)
    query = query.order_by(CorporateInvoiceDispute.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
