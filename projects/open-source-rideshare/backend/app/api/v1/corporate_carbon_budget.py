"""Corporate Carbon Budget & ESG Reporting endpoints.

Account-member endpoints (any active member):
  GET  /corporate/accounts/me/carbon-budget        — view budget config
  GET  /corporate/accounts/me/carbon-summary        — current-month carbon summary
  GET  /corporate/accounts/me/carbon-trend          — month-over-month trend

Account-admin endpoints (account admins only):
  PUT  /corporate/accounts/me/carbon-budget         — set/update budget
  GET  /corporate/accounts/me/carbon/employees      — per-employee carbon breakdown

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{id}/carbon-budget — view budget for any account
  GET  /admin/corporate/carbon/esg-report           — cross-account ESG summary
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_carbon_budget import (
    CarbonBudgetResponse,
    CarbonBudgetUpsert,
    CarbonSummaryResponse,
    CarbonTrendResponse,
    EmployeeCarbonBreakdownResponse,
    ESGReportResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_carbon_budget import (
    get_account_carbon_summary,
    get_carbon_trend,
    get_employee_carbon_breakdown,
    get_or_create_carbon_budget,
    get_platform_esg_report,
    update_carbon_budget,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-carbon-budget"])


# ---------------------------------------------------------------------------
# Internal helper
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
# Member: view carbon budget
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/carbon-budget",
    response_model=CarbonBudgetResponse,
    summary="Get carbon budget configuration for own corporate account",
)
async def get_my_carbon_budget(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the carbon budget configuration for the requesting user's account.

    Creates a default budget record (tracking_enabled=True, no ceiling) if
    none exists yet.  Accessible by any active member.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_or_create_carbon_budget(db, account_id)


# ---------------------------------------------------------------------------
# Admin: set/update carbon budget
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/carbon-budget",
    response_model=CarbonBudgetResponse,
    summary="Set or update the carbon budget for own corporate account (admin only)",
)
async def set_my_carbon_budget(
    payload: CarbonBudgetUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the monthly CO2 budget for the requesting user's account.

    Only account admins may call this endpoint.  Fields not included in the
    request body are left unchanged.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await update_carbon_budget(db, account_id, payload, admin_id=user.id)


# ---------------------------------------------------------------------------
# Member: current-month carbon summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/carbon-summary",
    response_model=CarbonSummaryResponse,
    summary="Get current-month carbon summary for own corporate account",
)
async def get_my_carbon_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current-month carbon footprint summary.

    Includes total CO2, green ride percentage, offset payments, and budget
    utilisation when a monthly budget ceiling is configured.  Accessible by
    any active member when tracking is enabled; admins always see the data.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_account_carbon_summary(db, account_id, requesting_user_id=user.id)


# ---------------------------------------------------------------------------
# Member: monthly carbon trend
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/carbon-trend",
    response_model=CarbonTrendResponse,
    summary="Get month-over-month carbon trend for own corporate account",
)
async def get_my_carbon_trend(
    months: int = Query(
        6, ge=1, le=24, description="Number of past calendar months to include"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return month-over-month carbon data for the last N calendar months.

    Data points are ordered newest-first.  Months with no corporate carbon
    records are omitted from the series.  Accessible by any active member
    when tracking is enabled.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_carbon_trend(
        db, account_id, requesting_user_id=user.id, months=months
    )


# ---------------------------------------------------------------------------
# Admin: per-employee carbon breakdown
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/carbon/employees",
    response_model=EmployeeCarbonBreakdownResponse,
    summary="Get per-employee carbon breakdown for own account (admin only)",
)
async def get_my_employee_carbon(
    period_start: date = Query(..., description="Inclusive start of analysis window"),
    period_end: date = Query(..., description="Inclusive end of analysis window"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return per-employee carbon footprint for a billing period.

    Ordered by CO2 descending (highest emitters first).  Only account admins
    may call this endpoint as it exposes individual employee travel data.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_employee_carbon_breakdown(
        db,
        account_id,
        requesting_user_id=user.id,
        period_start=period_start,
        period_end=period_end,
    )


# ---------------------------------------------------------------------------
# Platform admin: carbon budget for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/carbon-budget",
    response_model=CarbonBudgetResponse,
    summary="Admin: get carbon budget for any corporate account",
)
async def admin_get_carbon_budget(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the carbon budget configuration for any corporate account.

    Platform admin only.
    """
    return await get_or_create_carbon_budget(db, account_id)


# ---------------------------------------------------------------------------
# Platform admin: cross-account ESG report
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/carbon/esg-report",
    response_model=ESGReportResponse,
    summary="Admin: platform-wide corporate ESG carbon summary",
)
async def admin_get_esg_report(
    months: int = Query(
        12, ge=1, le=24, description="Number of past calendar months to include"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a platform-wide ESG carbon summary across all corporate accounts.

    Aggregates ride_carbon_records for every ride billed to a corporate account
    and presents monthly trend data alongside cumulative totals.  Intended for
    platform sustainability reporting and board-level ESG disclosures.

    Platform admin only.
    """
    return await get_platform_esg_report(db, months=months)
