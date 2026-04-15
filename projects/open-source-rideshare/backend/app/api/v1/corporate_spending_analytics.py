"""Corporate Spending Analytics endpoints.

Account-member endpoints (any active member):
  GET  /corporate/accounts/me/analytics/overview        — current-month, YTD, all-time totals
  GET  /corporate/accounts/me/analytics/monthly         — monthly trend (last N months)
  GET  /corporate/accounts/me/analytics/ride-patterns   — ride counts by hour and day-of-week

Account-admin endpoints (account admins only):
  GET  /corporate/accounts/me/analytics/employees       — top employee spenders for a period

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{id}/analytics/overview
  GET  /admin/corporate/accounts/{id}/analytics/monthly
  GET  /admin/corporate/accounts/{id}/analytics/employees
  GET  /admin/corporate/accounts/{id}/analytics/ride-patterns
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_spending_analytics import (
    EmployeeSpendBreakdownResponse,
    MonthlySpendTrendResponse,
    RidePatternResponse,
    SpendingOverviewResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_spending_analytics import (
    get_employee_spend_breakdown,
    get_monthly_spend_trend,
    get_ride_pattern_analytics,
    get_spending_overview,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-spending-analytics"])


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


# ---------------------------------------------------------------------------
# Member: spending overview
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/analytics/overview",
    response_model=SpendingOverviewResponse,
    summary="Get spending overview for own corporate account",
)
async def get_my_spending_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current-month, year-to-date, and all-time spend totals.

    Accessible by any active member of the corporate account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_spending_overview(db, account_id, requesting_user_id=user.id)


# ---------------------------------------------------------------------------
# Member: monthly spend trend
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/analytics/monthly",
    response_model=MonthlySpendTrendResponse,
    summary="Get monthly spend trend for own corporate account",
)
async def get_my_monthly_trend(
    months: int = Query(12, ge=1, le=24, description="Number of calendar months to include"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return month-over-month spend data for the last N calendar months.

    Data points are ordered newest-first.  Months with no rides are omitted.
    Accessible by any active member of the corporate account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_monthly_spend_trend(
        db, account_id, requesting_user_id=user.id, months=months
    )


# ---------------------------------------------------------------------------
# Member: ride pattern analytics
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/analytics/ride-patterns",
    response_model=RidePatternResponse,
    summary="Get ride patterns (hour/day) for own corporate account",
)
async def get_my_ride_patterns(
    period_start: date = Query(..., description="Inclusive start of analysis window"),
    period_end: date = Query(..., description="Inclusive end of analysis window"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return ride distribution by hour-of-day and day-of-week.

    All 24 hour buckets and all 7 day-of-week buckets are always returned,
    including zero-count buckets.  Accessible by any active member.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_ride_pattern_analytics(
        db, account_id, requesting_user_id=user.id,
        period_start=period_start, period_end=period_end,
    )


# ---------------------------------------------------------------------------
# Admin: employee spend breakdown
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/analytics/employees",
    response_model=EmployeeSpendBreakdownResponse,
    summary="Get top employee spenders for own corporate account (admin only)",
)
async def get_my_employee_spend(
    period_start: date = Query(..., description="Inclusive start of analysis window"),
    period_end: date = Query(..., description="Inclusive end of analysis window"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of employees to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return top employee spenders for the given period.

    Only account admins may call this endpoint as it reveals individual
    employee spending data.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_employee_spend_breakdown(
        db, account_id, requesting_user_id=user.id,
        period_start=period_start, period_end=period_end, limit=limit,
    )


# ---------------------------------------------------------------------------
# Platform admin: all four analytics endpoints for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/analytics/overview",
    response_model=SpendingOverviewResponse,
    summary="Admin: get spending overview for any corporate account",
)
async def admin_get_spending_overview(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return current-month, YTD, and all-time spend totals (platform admin)."""
    return await get_spending_overview(db, account_id, requesting_user_id=_admin.id)


@router.get(
    "/admin/corporate/accounts/{account_id}/analytics/monthly",
    response_model=MonthlySpendTrendResponse,
    summary="Admin: get monthly spend trend for any corporate account",
)
async def admin_get_monthly_trend(
    account_id: int,
    months: int = Query(12, ge=1, le=24),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return month-over-month spend data for any account (platform admin)."""
    return await get_monthly_spend_trend(
        db, account_id, requesting_user_id=_admin.id, months=months
    )


@router.get(
    "/admin/corporate/accounts/{account_id}/analytics/employees",
    response_model=EmployeeSpendBreakdownResponse,
    summary="Admin: get top employee spenders for any corporate account",
)
async def admin_get_employee_spend(
    account_id: int,
    period_start: date = Query(...),
    period_end: date = Query(...),
    limit: int = Query(10, ge=1, le=50),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return top employee spenders for any account (platform admin)."""
    return await get_employee_spend_breakdown(
        db, account_id, requesting_user_id=_admin.id,
        period_start=period_start, period_end=period_end, limit=limit,
    )


@router.get(
    "/admin/corporate/accounts/{account_id}/analytics/ride-patterns",
    response_model=RidePatternResponse,
    summary="Admin: get ride patterns for any corporate account",
)
async def admin_get_ride_patterns(
    account_id: int,
    period_start: date = Query(...),
    period_end: date = Query(...),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return ride distribution by hour and day-of-week for any account (platform admin)."""
    return await get_ride_pattern_analytics(
        db, account_id, requesting_user_id=_admin.id,
        period_start=period_start, period_end=period_end,
    )
