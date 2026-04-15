"""Corporate Invoice Dispute endpoints.

Member endpoints (authenticated member of the account):
  POST   /corporate/invoices/{invoice_id}/disputes           — submit a dispute
  GET    /corporate/invoices/{invoice_id}/disputes           — list disputes for invoice
  GET    /corporate/disputes/{dispute_id}                    — get a single dispute
  PUT    /corporate/disputes/{dispute_id}                    — update a dispute
  DELETE /corporate/disputes/{dispute_id}/withdraw           — withdraw a dispute

Admin endpoints (platform admin only):
  GET    /corporate/accounts/{account_id}/disputes           — list account disputes
  POST   /corporate/disputes/{dispute_id}/review             — mark under review
  POST   /corporate/disputes/{dispute_id}/resolve            — resolve a dispute
  GET    /admin/corporate/disputes                           — list all disputes
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_invoice import CorporateInvoice
from app.models.user import User
from app.schemas.corporate_invoice_dispute import (
    InvoiceDisputeListResponse,
    InvoiceDisputeResponse,
    ResolveDisputeRequest,
    ReviewDisputeRequest,
    SubmitDisputeRequest,
    UpdateDisputeRequest,
    WithdrawDisputeRequest,
)
from app.models.corporate_invoice_dispute import DisputeStatus
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_invoice_dispute import (
    get_dispute,
    get_dispute_by_invoice,
    list_account_disputes,
    list_all_disputes,
    mark_under_review,
    resolve_dispute,
    submit_dispute,
    update_dispute,
    withdraw_dispute,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-invoice-disputes"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Resolve the corporate account ID for an authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


async def _get_invoice_account_id(db: AsyncSession, invoice_id: int) -> int:
    """Return the account_id for the given invoice, or raise HTTP 404."""
    result = await db.execute(
        select(CorporateInvoice).where(CorporateInvoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )
    return invoice.account_id


# ---------------------------------------------------------------------------
# Member: submit a dispute for an invoice
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/invoices/{invoice_id}/disputes",
    response_model=InvoiceDisputeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a dispute for a corporate invoice",
)
async def submit_invoice_dispute(
    invoice_id: int,
    payload: SubmitDisputeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a formal dispute against a corporate invoice charge.

    The requesting user must be a member of the corporate account that owns
    the invoice.  Returns HTTP 404 when the invoice is not found or does not
    belong to the user's account.  Returns HTTP 409 when an active dispute
    already exists for the invoice.

    Member only.
    """
    account_id = await _get_member_account_id(db, user.id)
    return await submit_dispute(
        db,
        invoice_id=invoice_id,
        account_id=account_id,
        submitted_by_id=user.id,
        dispute_type=payload.dispute_type,
        description=payload.description,
        disputed_rides=payload.disputed_rides,
        disputed_amount_usd=payload.disputed_amount_usd,
    )


# ---------------------------------------------------------------------------
# Member: list disputes for an invoice
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/invoices/{invoice_id}/disputes",
    response_model=InvoiceDisputeListResponse,
    summary="List disputes for a corporate invoice",
)
async def list_invoice_disputes(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all disputes submitted for a specific invoice.

    The requesting user must be a member of the corporate account that owns
    the invoice.

    Member only.
    """
    account_id = await _get_member_account_id(db, user.id)
    records = await get_dispute_by_invoice(db, invoice_id=invoice_id, account_id=account_id)
    return InvoiceDisputeListResponse(disputes=list(records), total=len(records))


# ---------------------------------------------------------------------------
# Member: get a single dispute
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/disputes/{dispute_id}",
    response_model=InvoiceDisputeResponse,
    summary="Get a single corporate invoice dispute",
)
async def get_invoice_dispute(
    dispute_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single dispute by ID.

    The requesting user must be a member of the corporate account that owns
    the dispute.  Returns HTTP 404 when not found or when the user belongs to
    a different account.

    Member only.
    """
    account_id = await _get_member_account_id(db, user.id)
    dispute = await get_dispute(db, dispute_id)
    if dispute is None or dispute.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )
    return dispute


# ---------------------------------------------------------------------------
# Member: update a dispute
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/disputes/{dispute_id}",
    response_model=InvoiceDisputeResponse,
    summary="Update a pending corporate invoice dispute",
)
async def update_invoice_dispute(
    dispute_id: int,
    payload: UpdateDisputeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the fields of a pending dispute.

    Only disputes in 'submitted' status may be edited.  Returns HTTP 409 when
    the dispute is already under review or resolved.

    Member only.
    """
    account_id = await _get_member_account_id(db, user.id)
    return await update_dispute(
        db,
        dispute_id=dispute_id,
        account_id=account_id,
        **payload.model_dump(exclude_unset=True),
    )


# ---------------------------------------------------------------------------
# Member: withdraw a dispute
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/disputes/{dispute_id}/withdraw",
    response_model=InvoiceDisputeResponse,
    summary="Withdraw a corporate invoice dispute",
)
async def withdraw_invoice_dispute(
    dispute_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw a dispute before it is resolved.

    Members may withdraw disputes that are in 'submitted' or 'under_review'
    status.  Returns HTTP 409 when the dispute has already been resolved.

    Member only.
    """
    account_id = await _get_member_account_id(db, user.id)
    return await withdraw_dispute(db, dispute_id=dispute_id, account_id=account_id)


# ---------------------------------------------------------------------------
# Admin: list disputes for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/{account_id}/disputes",
    response_model=InvoiceDisputeListResponse,
    summary="Admin: list disputes for a corporate account",
)
async def admin_list_account_disputes(
    account_id: int,
    status: DisputeStatus | None = Query(None, description="Filter by dispute status"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all disputes for a specific corporate account.

    Supports optional filtering by status.  Ordered by most recently submitted
    first.

    Platform admin only.
    """
    records = await list_account_disputes(
        db, account_id=account_id, status_filter=status, skip=skip, limit=limit
    )
    return InvoiceDisputeListResponse(disputes=list(records), total=len(records))


# ---------------------------------------------------------------------------
# Admin: mark a dispute under review
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/disputes/{dispute_id}/review",
    response_model=InvoiceDisputeResponse,
    summary="Admin: mark a dispute as under review",
)
async def admin_mark_dispute_under_review(
    dispute_id: int,
    _payload: ReviewDisputeRequest = ReviewDisputeRequest(),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a dispute as under review.

    Returns HTTP 404 when the dispute is not found.  Returns HTTP 409 when
    the dispute has already been resolved or withdrawn.

    Platform admin only.
    """
    return await mark_under_review(db, dispute_id=dispute_id, reviewed_by_id=_admin.id)


# ---------------------------------------------------------------------------
# Admin: resolve a dispute
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/disputes/{dispute_id}/resolve",
    response_model=InvoiceDisputeResponse,
    summary="Admin: resolve a corporate invoice dispute",
)
async def admin_resolve_dispute(
    dispute_id: int,
    payload: ResolveDisputeRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a dispute as upheld or denied.

    Returns HTTP 404 when the dispute is not found.  Returns HTTP 409 when
    the dispute has already been resolved or withdrawn.

    Platform admin only.
    """
    return await resolve_dispute(
        db,
        dispute_id=dispute_id,
        resolved_by_id=_admin.id,
        resolution=payload.resolution,
        resolution_note=payload.resolution_note,
    )


# ---------------------------------------------------------------------------
# Admin: list all disputes across all accounts
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/disputes",
    response_model=InvoiceDisputeListResponse,
    summary="Admin: list all corporate invoice disputes",
)
async def admin_list_all_disputes(
    dispute_status: DisputeStatus | None = Query(None, alias="status", description="Filter by dispute status"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all disputes across all corporate accounts.

    Supports optional filtering by status.  Ordered by most recently submitted
    first.  Intended for platform-admin oversight and compliance dashboards.

    Platform admin only.
    """
    records = await list_all_disputes(db, status_filter=dispute_status, skip=skip, limit=limit)
    return InvoiceDisputeListResponse(disputes=list(records), total=len(records))
