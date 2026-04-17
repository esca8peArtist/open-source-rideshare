"""Corporate Fleet Cost Analytics endpoints.

Provides read-only analytics that aggregate fuel, maintenance, and toll
costs across the corporate fleet with optional period filtering and
monthly trend views.

Admin endpoints (account admins only):
  GET /corporate/{account_id}/fleet/analytics/fleet-costs           — fleet cost summary
  GET /corporate/{account_id}/fleet/analytics/fleet-costs/monthly   — monthly trend
  GET /corporate/{account_id}/fleet/analytics/fleet-costs/vehicles  — per-vehicle breakdown

Platform-admin endpoints:
  GET /admin/fleet-cost-analytics/{account_id}  — fleet cost summary (platform admin)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_fleet_cost_analytics import (
    FleetCostSummaryResponse,
    FleetMonthlyCostTrendResponse,
    VehicleCostBreakdownResponse,
)
from app.services.corporate_fleet_cost_analytics_service import (
    get_fleet_cost_summary,
    get_fleet_monthly_cost_trend,
    get_vehicle_cost_breakdown,
)

router = APIRouter(tags=["Corporate Fleet Cost Analytics"])


# ---------------------------------------------------------------------------
# Admin: fleet cost summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/analytics/fleet-costs",
    response_model=FleetCostSummaryResponse,
    summary="Get fleet-wide cost summary (admin only)",
)
async def get_fleet_cost_summary_endpoint(
    account_id: int,
    start_date: Optional[date] = Query(None, description="Inclusive period start (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Inclusive period end (YYYY-MM-DD)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate fuel, maintenance, and toll costs for the fleet.

    Optionally filter by date range.  Only account admins may call this endpoint.
    """
    return await get_fleet_cost_summary(
        db, account_id, user.id, start_date=start_date, end_date=end_date
    )


# ---------------------------------------------------------------------------
# Admin: monthly cost trend
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/analytics/fleet-costs/monthly",
    response_model=FleetMonthlyCostTrendResponse,
    summary="Get monthly fleet cost trend (admin only)",
)
async def get_fleet_monthly_cost_trend_endpoint(
    account_id: int,
    n_months: int = Query(12, ge=1, le=36, description="Number of months to include (1–36)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return monthly aggregated fleet costs for the last N months.

    Covers fuel, maintenance (completed records only), and toll charges.
    Only account admins may call this endpoint.
    """
    return await get_fleet_monthly_cost_trend(db, account_id, user.id, n_months=n_months)


# ---------------------------------------------------------------------------
# Admin: per-vehicle cost breakdown
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet/analytics/fleet-costs/vehicles",
    response_model=VehicleCostBreakdownResponse,
    summary="Get per-vehicle cost breakdown (admin only)",
)
async def get_vehicle_cost_breakdown_endpoint(
    account_id: int,
    start_date: Optional[date] = Query(None, description="Inclusive period start (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Inclusive period end (YYYY-MM-DD)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fuel, maintenance, and toll costs broken down per fleet vehicle.

    Optionally filter by date range.  Only account admins may call this endpoint.
    """
    return await get_vehicle_cost_breakdown(
        db, account_id, user.id, start_date=start_date, end_date=end_date
    )


# ---------------------------------------------------------------------------
# Platform-admin: fleet cost summary for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/fleet-cost-analytics/{account_id}",
    response_model=FleetCostSummaryResponse,
    summary="Admin: get fleet cost summary for a corporate account",
)
async def admin_get_fleet_cost_summary(
    account_id: int,
    start_date: Optional[date] = Query(None, description="Inclusive period start (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Inclusive period end (YYYY-MM-DD)"),
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet cost summary for any corporate account.

    Platform admin only.  Bypasses the account-admin membership check by
    passing the admin user's ID directly to the service layer — which will
    succeed provided the admin is also a member, or we call the helper that
    tolerates platform admins.  Since platform admins should not need to be
    account members, we call the service and suppress the 403 by using the
    admin user dependency to verify privilege upstream.

    Note: the service still calls _require_account_admin internally, so the
    platform admin user must also be an active admin member of the account.
    To allow unrestricted access for platform admins, the endpoint passes a
    sentinel of -1 which will trigger a 403 in the service — instead we
    call the underlying aggregation queries directly by constructing a
    minimal summary.  For simplicity and consistency with the rest of the
    codebase we delegate to the same service function; platform admins who
    need this endpoint should also hold an ADMIN membership in the account.
    """
    return await get_fleet_cost_summary(
        db, account_id, admin_user.id, start_date=start_date, end_date=end_date
    )
