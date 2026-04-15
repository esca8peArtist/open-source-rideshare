"""Router for the driver payout / disbursement feature.

Driver endpoints (require DRIVER role):
  GET  /drivers/me/payouts/pending-earnings  — calculate unpaid earnings
  GET  /drivers/me/payouts                  — list payout history
  POST /drivers/me/payouts                  — request a payout

Admin endpoints (require ADMIN role):
  GET  /admin/payouts                       — list all payouts
  GET  /admin/payouts/stats                 — aggregate stats
  POST /admin/payouts/{payout_id}/process   — mark completed
  POST /admin/payouts/{payout_id}/fail      — mark failed
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver_payout import DriverPayoutMethod, DriverPayoutStatus
from app.models.user import User
from app.schemas.driver_payout import (
    AdminFailPayoutRequest,
    AdminPayoutResponse,
    AdminProcessPayoutRequest,
    DriverPayoutResponse,
    PayoutRequestRequest,
    PayoutStatsResponse,
    PendingEarningsResponse,
)
from app.services.driver_payouts import (
    calculate_pending_earnings,
    fail_payout,
    get_all_payouts,
    get_driver_payouts,
    get_payout_stats,
    process_payout,
    request_payout,
)

router = APIRouter(tags=["driver-payouts"])


def _default_period() -> tuple[date, date]:
    """Return (7 days ago, today) as the default earning period."""
    today = date.today()
    return today - timedelta(days=7), today


# ---------------------------------------------------------------------------
# Driver: pending earnings
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/payouts/pending-earnings",
    response_model=PendingEarningsResponse,
    summary="Get pending (unpaid) earnings for a date range",
)
async def get_pending_earnings(
    period_start: date | None = Query(
        default=None,
        description="Start of earning period (inclusive). Defaults to 7 days ago.",
    ),
    period_end: date | None = Query(
        default=None,
        description="End of earning period (inclusive). Defaults to today.",
    ),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Calculate unpaid earnings for the authenticated driver over a date range."""
    default_start, default_end = _default_period()
    start = period_start or default_start
    end = period_end or default_end

    earnings = await calculate_pending_earnings(db, user.id, start, end)
    return PendingEarningsResponse(
        driver_id=user.id,
        period_start=start,
        period_end=end,
        gross_usd=earnings["gross_usd"],
        platform_fee_usd=earnings["platform_fee_usd"],
        net_usd=earnings["net_usd"],
        ride_count=earnings["ride_count"],
        commission_pct=earnings["commission_pct"],
    )


# ---------------------------------------------------------------------------
# Driver: payout history
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/payouts",
    response_model=list[DriverPayoutResponse],
    summary="List my payout history",
)
async def list_my_payouts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated payout history for the authenticated driver."""
    payouts = await get_driver_payouts(db, user.id, skip=skip, limit=limit)
    return payouts


# ---------------------------------------------------------------------------
# Driver: request payout
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/payouts",
    response_model=DriverPayoutResponse,
    status_code=201,
    summary="Request a payout",
)
async def request_my_payout(
    req: PayoutRequestRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Request a payout for the authenticated driver.

    Returns 400 if there are no earnings to pay out, or if an overlapping
    pending/processing payout already exists.
    """
    default_start, default_end = _default_period()
    start = req.period_start or default_start
    end = req.period_end or default_end
    method = req.method or DriverPayoutMethod.stripe_transfer

    payout = await request_payout(db, user.id, start, end, method)
    return payout


# ---------------------------------------------------------------------------
# Admin: list all payouts
# ---------------------------------------------------------------------------


@router.get(
    "/admin/payouts",
    response_model=list[AdminPayoutResponse],
    summary="Admin: list all payouts",
)
async def admin_list_payouts(
    status: DriverPayoutStatus | None = Query(
        default=None, description="Filter by payout status."
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all payouts, optionally filtered by status."""
    payouts = await get_all_payouts(db, status_filter=status, skip=skip, limit=limit)
    return payouts


# ---------------------------------------------------------------------------
# Admin: aggregate stats
# ---------------------------------------------------------------------------


@router.get(
    "/admin/payouts/stats",
    response_model=PayoutStatsResponse,
    summary="Admin: aggregate payout statistics",
)
async def admin_payout_stats(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate payout statistics across all drivers."""
    return await get_payout_stats(db)


# ---------------------------------------------------------------------------
# Admin: process a payout
# ---------------------------------------------------------------------------


@router.post(
    "/admin/payouts/{payout_id}/process",
    response_model=AdminPayoutResponse,
    summary="Admin: process a payout (mark completed)",
)
async def admin_process_payout(
    payout_id: int,
    req: AdminProcessPayoutRequest | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Move a pending payout through processing to completed."""
    notes = req.notes if req else None
    payout = await process_payout(db, payout_id, admin_notes=notes)
    return payout


# ---------------------------------------------------------------------------
# Admin: fail a payout
# ---------------------------------------------------------------------------


@router.post(
    "/admin/payouts/{payout_id}/fail",
    response_model=AdminPayoutResponse,
    summary="Admin: mark a payout as failed",
)
async def admin_fail_payout(
    payout_id: int,
    req: AdminFailPayoutRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a pending or processing payout as failed with an explanation."""
    payout = await fail_payout(db, payout_id, reason=req.reason)
    return payout
