"""Service layer for the Corporate Cost Centers feature.

Companies can create named cost centers (departments, projects, teams) and
tag rides to them.  Admins view per-cost-center spend reports.

Public surface
--------------
create_cost_center(db, account_id, data, requesting_user_id)
get_cost_center(db, cost_center_id, account_id)
list_cost_centers(db, account_id, active_only=True)
update_cost_center(db, cost_center_id, account_id, data, requesting_user_id)
deactivate_cost_center(db, cost_center_id, account_id, requesting_user_id)
get_cost_center_spend(db, cost_center_id, account_id, period_start, period_end)
list_account_spend_by_cost_center(db, account_id, period_start, period_end)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.ride import Ride

MAX_COST_CENTERS_PER_ACCOUNT = 100


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


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 if the user is not an active member of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _get_cost_center(
    db: AsyncSession, cost_center_id: int, account_id: int
) -> CorporateCostCenter:
    """Fetch a cost center; raise 404 if not found or account mismatch."""
    result = await db.execute(
        select(CorporateCostCenter).where(
            CorporateCostCenter.id == cost_center_id,
            CorporateCostCenter.account_id == account_id,
        )
    )
    cc = result.scalar_one_or_none()
    if cc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cost center not found.",
        )
    return cc


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_cost_center(
    db: AsyncSession,
    account_id: int,
    data,
    requesting_user_id: int,
) -> CorporateCostCenter:
    """Create a new cost center for an account.

    Rules:
    - Requesting user must be an account admin.
    - Code must be unique within the account (case-normalised to UPPER in schema).
    - Account may not exceed MAX_COST_CENTERS_PER_ACCOUNT active cost centers.

    Raises:
        HTTPException 400: Duplicate code or max-count reached.
        HTTPException 403: Requesting user is not an account admin.
    """
    await _require_account_admin(db, account_id, requesting_user_id)

    # Enforce account-scoped code uniqueness
    dup_result = await db.execute(
        select(CorporateCostCenter).where(
            CorporateCostCenter.account_id == account_id,
            CorporateCostCenter.code == data.code,
        )
    )
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A cost center with code '{data.code}' already exists for this account.",
        )

    # Enforce max cost-center count
    count_result = await db.execute(
        select(func.count(CorporateCostCenter.id)).where(
            CorporateCostCenter.account_id == account_id,
            CorporateCostCenter.is_active.is_(True),
        )
    )
    count = count_result.scalar() or 0
    if count >= MAX_COST_CENTERS_PER_ACCOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Account has reached the maximum of {MAX_COST_CENTERS_PER_ACCOUNT} cost centers.",
        )

    cc = CorporateCostCenter(
        account_id=account_id,
        name=data.name,
        code=data.code,
        description=getattr(data, "description", None),
        monthly_budget=getattr(data, "monthly_budget", None),
        is_active=True,
    )
    db.add(cc)
    await db.commit()
    await db.refresh(cc)
    return cc


async def get_cost_center(
    db: AsyncSession,
    cost_center_id: int,
    account_id: int,
) -> CorporateCostCenter:
    """Return a cost center by ID, scoped to the account.

    Raises:
        HTTPException 404: Not found or account mismatch.
    """
    return await _get_cost_center(db, cost_center_id, account_id)


async def list_cost_centers(
    db: AsyncSession,
    account_id: int,
    *,
    active_only: bool = True,
) -> Sequence[CorporateCostCenter]:
    """Return cost centers for an account, ordered by name.

    Args:
        active_only: When True (default), returns only is_active=True rows.
    """
    q = select(CorporateCostCenter).where(
        CorporateCostCenter.account_id == account_id
    )
    if active_only:
        q = q.where(CorporateCostCenter.is_active.is_(True))
    q = q.order_by(CorporateCostCenter.name.asc())
    result = await db.execute(q)
    return result.scalars().all()


async def update_cost_center(
    db: AsyncSession,
    cost_center_id: int,
    account_id: int,
    data,
    requesting_user_id: int,
) -> CorporateCostCenter:
    """Partial update of a cost center (admin only).

    Raises:
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Cost center not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    cc = await _get_cost_center(db, cost_center_id, account_id)

    if data.name is not None:
        cc.name = data.name
    if data.description is not None:
        cc.description = data.description
    if data.monthly_budget is not None:
        cc.monthly_budget = data.monthly_budget
    if data.is_active is not None:
        cc.is_active = data.is_active

    db.add(cc)
    await db.commit()
    await db.refresh(cc)
    return cc


async def deactivate_cost_center(
    db: AsyncSession,
    cost_center_id: int,
    account_id: int,
    requesting_user_id: int,
) -> CorporateCostCenter:
    """Soft-delete a cost center (sets is_active=False).

    Historical rides retain their cost_center_id assignment.

    Raises:
        HTTPException 400: Cost center already inactive.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Cost center not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    cc = await _get_cost_center(db, cost_center_id, account_id)

    if not cc.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cost center is already inactive.",
        )

    cc.is_active = False
    db.add(cc)
    await db.commit()
    await db.refresh(cc)
    return cc


# ---------------------------------------------------------------------------
# Spend reporting
# ---------------------------------------------------------------------------


async def get_cost_center_spend(
    db: AsyncSession,
    cost_center_id: int,
    account_id: int,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    """Aggregate ride spend for a single cost center.

    Args:
        period_start: Inclusive start date filter (completed_at >= period_start).
        period_end:   Inclusive end date filter (completed_at <= period_end).

    Returns:
        dict with keys: cost_center_id, cost_center_name, cost_center_code,
        period_start, period_end, total_rides, total_spend,
        monthly_budget, budget_utilization_pct.
    """
    cc = await _get_cost_center(db, cost_center_id, account_id)

    q = select(
        func.count(Ride.id).label("total_rides"),
        func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend"),
    ).where(
        Ride.cost_center_id == cost_center_id,
        Ride.actual_fare.is_not(None),
        Ride.completed_at.is_not(None),
    )

    if period_start is not None:
        q = q.where(func.date(Ride.completed_at) >= period_start)
    if period_end is not None:
        q = q.where(func.date(Ride.completed_at) <= period_end)

    result = await db.execute(q)
    row = result.one()

    total_rides = row.total_rides or 0
    total_spend = Decimal(str(row.total_spend or 0))

    budget_utilization_pct: float | None = None
    if cc.monthly_budget and cc.monthly_budget > 0:
        budget_utilization_pct = float((total_spend / cc.monthly_budget) * 100)

    return {
        "cost_center_id": cc.id,
        "cost_center_name": cc.name,
        "cost_center_code": cc.code,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "total_rides": total_rides,
        "total_spend": total_spend,
        "monthly_budget": cc.monthly_budget,
        "budget_utilization_pct": budget_utilization_pct,
    }


async def list_account_spend_by_cost_center(
    db: AsyncSession,
    account_id: int,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[dict]:
    """Return spend breakdown across all cost centers for an account.

    Cost centers with no rides in the period are included with zero totals.
    Rows are ordered by total_spend descending.

    Args:
        period_start: Inclusive start date filter.
        period_end:   Inclusive end date filter.

    Returns:
        list of dicts (same shape as get_cost_center_spend).
    """
    # Fetch all cost centers for the account (including inactive, for history)
    cc_result = await db.execute(
        select(CorporateCostCenter)
        .where(CorporateCostCenter.account_id == account_id)
        .order_by(CorporateCostCenter.name.asc())
    )
    cost_centers = cc_result.scalars().all()

    if not cost_centers:
        return []

    # Build a spend lookup: cost_center_id → (total_rides, total_spend)
    spend_q = select(
        Ride.cost_center_id,
        func.count(Ride.id).label("total_rides"),
        func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend"),
    ).where(
        Ride.cost_center_id.in_([cc.id for cc in cost_centers]),
        Ride.actual_fare.is_not(None),
        Ride.completed_at.is_not(None),
    )

    if period_start is not None:
        spend_q = spend_q.where(func.date(Ride.completed_at) >= period_start)
    if period_end is not None:
        spend_q = spend_q.where(func.date(Ride.completed_at) <= period_end)

    spend_q = spend_q.group_by(Ride.cost_center_id)
    spend_result = await db.execute(spend_q)
    spend_rows = {row.cost_center_id: row for row in spend_result.all()}

    summaries = []
    for cc in cost_centers:
        row = spend_rows.get(cc.id)
        total_rides = row.total_rides if row else 0
        total_spend = Decimal(str(row.total_spend)) if row else Decimal("0.00")

        budget_utilization_pct: float | None = None
        if cc.monthly_budget and cc.monthly_budget > 0:
            budget_utilization_pct = float((total_spend / cc.monthly_budget) * 100)

        summaries.append(
            {
                "cost_center_id": cc.id,
                "cost_center_name": cc.name,
                "cost_center_code": cc.code,
                "period_start": period_start.isoformat() if period_start else None,
                "period_end": period_end.isoformat() if period_end else None,
                "total_rides": total_rides,
                "total_spend": total_spend,
                "monthly_budget": cc.monthly_budget,
                "budget_utilization_pct": budget_utilization_pct,
            }
        )

    summaries.sort(key=lambda x: x["total_spend"], reverse=True)
    return summaries
