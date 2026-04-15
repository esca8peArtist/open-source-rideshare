"""Corporate Data Export endpoints.

Account-admin endpoints (account admins only):
  GET  /corporate/accounts/me/export/rides          — filtered ride CSV export
  GET  /corporate/accounts/me/export/invoices/{id}  — invoice line items CSV

Account-member endpoints (any active member):
  GET  /corporate/accounts/me/export/invoices/{id}  — see above (member-level)

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{id}/export/rides
  GET  /admin/corporate/accounts/{id}/export/invoices/{invoice_id}
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_data_export import (
    export_corporate_rides_csv,
    export_invoice_csv,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-data-export"])


# ---------------------------------------------------------------------------
# Internal helper: resolve the calling user's account_id
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _csv_response(csv_content: str, filename: str) -> StreamingResponse:
    """Wrap a CSV string in a StreamingResponse with correct headers."""
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _rides_filename(account_id: int, start_date: date | None, end_date: date | None) -> str:
    """Generate a timestamped filename for a rides CSV export."""
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    if start_date and end_date:
        return f"corporate_{account_id}_rides_{start_date}_{end_date}.csv"
    return f"corporate_{account_id}_rides_{now_str}.csv"


def _invoice_filename(account_id: int, invoice_id: int) -> str:
    return f"corporate_{account_id}_invoice_{invoice_id}.csv"


# ---------------------------------------------------------------------------
# Admin: export rides
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/export/rides",
    summary="Export corporate ride data as CSV (admin only)",
    response_class=StreamingResponse,
)
async def export_my_rides_csv(
    start_date: date | None = Query(None, description="Inclusive start date filter (ride.completed_at)"),
    end_date: date | None = Query(None, description="Inclusive end date filter (ride.completed_at)"),
    cost_center_id: int | None = Query(None, description="Filter to rides tagged with this cost center"),
    trip_purpose_id: int | None = Query(None, description="Filter to rides tagged with this trip purpose"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all completed corporate rides as a CSV file.

    Only account admins may call this endpoint. The export includes rider
    and driver names, cost-center and trip-purpose tags, fare breakdowns,
    and distance/duration. All filters are optional and can be combined.
    """
    account_id = await _resolve_account_id(db, user.id)
    csv_content = await export_corporate_rides_csv(
        db,
        account_id=account_id,
        requesting_user_id=user.id,
        start_date=start_date,
        end_date=end_date,
        cost_center_id=cost_center_id,
        trip_purpose_id=trip_purpose_id,
    )
    return _csv_response(csv_content, _rides_filename(account_id, start_date, end_date))


# ---------------------------------------------------------------------------
# Member: export invoice line items
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/export/invoices/{invoice_id}",
    summary="Export invoice line items as CSV (any member)",
    response_class=StreamingResponse,
)
async def export_my_invoice_csv(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export ride-level line items for a specific invoice as a CSV file.

    Accessible by any active member of the corporate account.  The export
    contains one row per completed ride within the invoice's billing period,
    with cost-center and trip-purpose annotations.
    """
    account_id = await _resolve_account_id(db, user.id)
    csv_content = await export_invoice_csv(
        db,
        invoice_id=invoice_id,
        account_id=account_id,
        requesting_user_id=user.id,
    )
    return _csv_response(csv_content, _invoice_filename(account_id, invoice_id))


# ---------------------------------------------------------------------------
# Platform admin: export rides for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/export/rides",
    summary="Admin: export ride data for any corporate account",
    response_class=StreamingResponse,
)
async def admin_export_rides_csv(
    account_id: int,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    cost_center_id: int | None = Query(None),
    trip_purpose_id: int | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export completed rides for any corporate account (platform admin)."""
    csv_content = await export_corporate_rides_csv(
        db,
        account_id=account_id,
        requesting_user_id=_admin.id,
        start_date=start_date,
        end_date=end_date,
        cost_center_id=cost_center_id,
        trip_purpose_id=trip_purpose_id,
    )
    return _csv_response(csv_content, _rides_filename(account_id, start_date, end_date))


# ---------------------------------------------------------------------------
# Platform admin: export invoice line items for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/export/invoices/{invoice_id}",
    summary="Admin: export invoice line items for any corporate account",
    response_class=StreamingResponse,
)
async def admin_export_invoice_csv(
    account_id: int,
    invoice_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export invoice line items for any corporate account (platform admin)."""
    csv_content = await export_invoice_csv(
        db,
        invoice_id=invoice_id,
        account_id=account_id,
        requesting_user_id=_admin.id,
    )
    return _csv_response(csv_content, _invoice_filename(account_id, invoice_id))
