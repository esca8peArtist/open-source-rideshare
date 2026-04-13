"""Admin financial reconciliation API.

All endpoints require admin authentication.

Endpoints:
  GET /admin/financial-reconciliation/summary       — platform revenue summary
  GET /admin/financial-reconciliation/export        — per-ride CSV export
  GET /admin/financial-reconciliation/payout-status — driver payout records
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.services.admin_financials import (
    export_reconciliation_csv,
    get_financial_summary,
    get_payout_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/financial-reconciliation",
    tags=["admin-financials"],
)

_VALID_PAYOUT_STATUSES = {"pending", "processing", "completed", "failed"}


def _parse_date(value: str | None, param_name: str) -> date:
    """Parse an ISO date string; raise 422 on bad format."""
    if value is None:
        raise HTTPException(
            status_code=422,
            detail=f"Query parameter '{param_name}' is required (ISO date: YYYY-MM-DD)",
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format for '{param_name}'. Expected YYYY-MM-DD, got: {value!r}",
        )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    summary="Platform financial reconciliation summary",
    description=(
        "Returns an aggregated financial overview for the specified date range. "
        "Includes gross platform revenue, total fares, tips, promo discounts, "
        "refunds issued, driver payouts, net platform revenue, and a daily breakdown. "
        "Requires admin authentication."
    ),
)
async def financial_summary(
    start_date: str = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Platform-level financial summary for the given date range."""
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )
    return await get_financial_summary(db, start_date=start, end_date=end)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export per-ride financial data as CSV",
    description=(
        "Returns a CSV file of per-ride financial data for the date range. "
        "Columns: date, ride_id, rider_id, driver_id, fare, tip, promo_discount, "
        "platform_fee, driver_payout, refund_amount, net_platform. "
        "Requires admin authentication."
    ),
)
async def export_reconciliation(
    start_date: str = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """CSV export of per-ride financial data for reconciliation."""
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )
    csv_content = await export_reconciliation_csv(db, start_date=start, end_date=end)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    filename = f"financial_reconciliation_{start_date}_{end_date}_{timestamp}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Payout status
# ---------------------------------------------------------------------------


@router.get(
    "/payout-status",
    summary="Driver payout status listing",
    description=(
        "Returns driver payout records for the given date range, optionally filtered "
        "by status (pending/processing/completed/failed). "
        "Requires admin authentication."
    ),
)
async def payout_status(
    start_date: str = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
    status: str | None = Query(
        None,
        description="Filter by payout status: pending, processing, completed, or failed",
    ),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Driver payout records filtered by date range and optional status."""
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )
    if status is not None and status not in _VALID_PAYOUT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_PAYOUT_STATUSES))}",
        )
    return await get_payout_status(db, start_date=start, end_date=end, status=status)
