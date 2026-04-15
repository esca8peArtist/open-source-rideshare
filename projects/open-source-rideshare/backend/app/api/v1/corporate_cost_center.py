"""Corporate Cost Center API endpoints.

Member endpoints (require active corporate account membership):
  POST   /corporate/accounts/me/cost-centers                      — create (admin)
  GET    /corporate/accounts/me/cost-centers                      — list
  GET    /corporate/accounts/me/cost-centers/{id}                 — get
  PATCH  /corporate/accounts/me/cost-centers/{id}                 — update (admin)
  DELETE /corporate/accounts/me/cost-centers/{id}                 — deactivate (admin)
  GET    /corporate/accounts/me/cost-centers/{id}/spend           — spend report (admin)
  GET    /corporate/accounts/me/cost-centers/spend                — all-centers spend (admin)

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/cost-centers            — list
  GET    /admin/corporate/accounts/{account_id}/cost-centers/{id}/spend — spend report
  GET    /admin/corporate/accounts/{account_id}/cost-centers/spend      — all-centers spend
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_cost_center import (
    CorporateCostCenterCreate,
    CorporateCostCenterResponse,
    CorporateCostCenterUpdate,
    CostCenterSpendSummary,
)
from app.services.corporate_cost_center import (
    create_cost_center,
    deactivate_cost_center,
    get_cost_center,
    get_cost_center_spend,
    list_account_spend_by_cost_center,
    list_cost_centers,
    update_cost_center,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-cost-centers"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID the user belongs to.

    Raises HTTP 404 if the user is not an active member of any account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return membership.account_id


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/cost-centers",
    response_model=CorporateCostCenterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cost center for your corporate account",
)
async def create_my_cost_center(
    data: CorporateCostCenterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new cost center (department, project, or team).

    Only account admins may create cost centers.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await create_cost_center(
        db, account_id, data, requesting_user_id=current_user.id
    )


@router.get(
    "/corporate/accounts/me/cost-centers",
    response_model=list[CorporateCostCenterResponse],
    summary="List cost centers for your corporate account",
)
async def list_my_cost_centers(
    active_only: bool = Query(True, description="Return only active cost centers."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all cost centers for the caller's corporate account."""
    account_id = await _get_member_account_id(db, current_user.id)
    return await list_cost_centers(db, account_id, active_only=active_only)


@router.get(
    "/corporate/accounts/me/cost-centers/spend",
    response_model=list[CostCenterSpendSummary],
    summary="Per-cost-center spend breakdown for your account",
)
async def my_account_spend_breakdown(
    period_start: date | None = Query(None, description="Filter rides from this date (inclusive)."),
    period_end: date | None = Query(None, description="Filter rides to this date (inclusive)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return spend totals broken down by cost center for the caller's account.

    Only account admins may view spend reports.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    # Admin check done inside service but surface a clean 403 here too
    from app.services.corporate_cost_center import _require_account_admin
    await _require_account_admin(db, account_id, current_user.id)
    return await list_account_spend_by_cost_center(
        db, account_id, period_start=period_start, period_end=period_end
    )


@router.get(
    "/corporate/accounts/me/cost-centers/{cost_center_id}",
    response_model=CorporateCostCenterResponse,
    summary="Get a specific cost center",
)
async def get_my_cost_center(
    cost_center_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a cost center by ID, scoped to the caller's account."""
    account_id = await _get_member_account_id(db, current_user.id)
    return await get_cost_center(db, cost_center_id, account_id)


@router.patch(
    "/corporate/accounts/me/cost-centers/{cost_center_id}",
    response_model=CorporateCostCenterResponse,
    summary="Update a cost center",
)
async def update_my_cost_center(
    cost_center_id: int,
    data: CorporateCostCenterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update a cost center.  Only account admins may update."""
    account_id = await _get_member_account_id(db, current_user.id)
    return await update_cost_center(
        db, cost_center_id, account_id, data, requesting_user_id=current_user.id
    )


@router.delete(
    "/corporate/accounts/me/cost-centers/{cost_center_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a cost center",
)
async def deactivate_my_cost_center(
    cost_center_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a cost center (sets is_active=False).

    Historical ride assignments are preserved.  Only account admins may
    deactivate cost centers.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    await deactivate_cost_center(
        db, cost_center_id, account_id, requesting_user_id=current_user.id
    )


@router.get(
    "/corporate/accounts/me/cost-centers/{cost_center_id}/spend",
    response_model=CostCenterSpendSummary,
    summary="Spend report for a single cost center",
)
async def get_my_cost_center_spend(
    cost_center_id: int,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return ride count and total spend for a specific cost center.

    Only account admins may view spend reports.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    from app.services.corporate_cost_center import _require_account_admin
    await _require_account_admin(db, account_id, current_user.id)
    return await get_cost_center_spend(
        db,
        cost_center_id,
        account_id,
        period_start=period_start,
        period_end=period_end,
    )


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/cost-centers",
    response_model=list[CorporateCostCenterResponse],
    summary="[Admin] List cost centers for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_cost_centers(
    account_id: int,
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """List cost centers for any corporate account (platform admin only)."""
    return await list_cost_centers(db, account_id, active_only=active_only)


@router.get(
    "/admin/corporate/accounts/{account_id}/cost-centers/spend",
    response_model=list[CostCenterSpendSummary],
    summary="[Admin] Per-cost-center spend breakdown for any account",
    dependencies=[Depends(require_admin)],
)
async def admin_account_spend_breakdown(
    account_id: int,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return spend totals by cost center for any account (platform admin only)."""
    return await list_account_spend_by_cost_center(
        db, account_id, period_start=period_start, period_end=period_end
    )


@router.get(
    "/admin/corporate/accounts/{account_id}/cost-centers/{cost_center_id}/spend",
    response_model=CostCenterSpendSummary,
    summary="[Admin] Spend report for a single cost center",
    dependencies=[Depends(require_admin)],
)
async def admin_cost_center_spend(
    account_id: int,
    cost_center_id: int,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return spend data for a specific cost center (platform admin only)."""
    return await get_cost_center_spend(
        db,
        cost_center_id,
        account_id,
        period_start=period_start,
        period_end=period_end,
    )
