"""Service layer for the Corporate Budget Alerts feature.

Admins configure percentage-based alert thresholds on cost centers or the
overall corporate account.  When spend crosses the threshold for a billing
cycle, an alert record transitions to ``triggered``.

Public surface
--------------
create_budget_alert(db, account_id, data)
get_budget_alert(db, account_id, alert_id)
list_budget_alerts(db, account_id, scope=None, status=None, skip=0, limit=50)
update_budget_alert(db, account_id, alert_id, data)
delete_budget_alert(db, account_id, alert_id)
acknowledge_alert(db, account_id, alert_id, user_id)
evaluate_budget_alerts(db, account_id, billing_month)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount
from app.models.corporate_budget_alert import (
    BudgetAlertScope,
    BudgetAlertStatus,
    CorporateBudgetAlert,
)
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.ride import Ride


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_alert(
    db: AsyncSession, account_id: int, alert_id: uuid.UUID
) -> CorporateBudgetAlert:
    """Fetch a budget alert; raise 404 if not found or account mismatch."""
    result = await db.execute(
        select(CorporateBudgetAlert).where(
            CorporateBudgetAlert.id == alert_id,
            CorporateBudgetAlert.corporate_account_id == account_id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Budget alert not found.",
        )
    return alert


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
            detail="Cost center not found or does not belong to this account.",
        )
    return cc


async def _get_account(db: AsyncSession, account_id: int) -> BusinessAccount:
    """Fetch a business account; raise 404 if not found."""
    result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )
    return account


async def _get_cost_center_spend(
    db: AsyncSession, cost_center_id: int, billing_month: date
) -> Decimal:
    """Return total ride spend for a cost center in a given billing month."""
    month_start = billing_month.replace(day=1)
    if billing_month.month == 12:
        month_end = billing_month.replace(year=billing_month.year + 1, month=1, day=1)
    else:
        month_end = billing_month.replace(month=billing_month.month + 1, day=1)

    result = await db.execute(
        select(
            func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend")
        ).where(
            Ride.cost_center_id == cost_center_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date_trunc("month", Ride.completed_at) == func.date_trunc(
                "month", month_start
            ),
        )
    )
    row = result.one()
    return Decimal(str(row.total_spend or 0))


async def _get_account_spend(
    db: AsyncSession, account_id: int, billing_month: date
) -> Decimal:
    """Return total ride spend for a corporate account in a given billing month."""
    month_start = billing_month.replace(day=1)

    result = await db.execute(
        select(
            func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend")
        ).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            func.date_trunc("month", Ride.completed_at) == func.date_trunc(
                "month", month_start
            ),
        )
    )
    row = result.one()
    return Decimal(str(row.total_spend or 0))


def _build_response_dict(alert: CorporateBudgetAlert) -> dict:
    """Enrich an alert with cost center name/code for response serialisation."""
    d = {
        "id": alert.id,
        "corporate_account_id": alert.corporate_account_id,
        "scope": alert.scope,
        "cost_center_id": alert.cost_center_id,
        "cost_center_code": None,
        "cost_center_name": None,
        "threshold_pct": alert.threshold_pct,
        "label": alert.label,
        "status": alert.status,
        "triggered_at": alert.triggered_at,
        "acknowledged_at": alert.acknowledged_at,
        "acknowledged_by_id": alert.acknowledged_by_id,
        "billing_month": alert.billing_month,
        "spend_at_trigger_usd": alert.spend_at_trigger_usd,
        "budget_at_trigger_usd": alert.budget_at_trigger_usd,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }
    if alert.cost_center is not None:
        d["cost_center_code"] = alert.cost_center.code
        d["cost_center_name"] = alert.cost_center.name
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_budget_alert(
    db: AsyncSession,
    account_id: int,
    data,
) -> CorporateBudgetAlert:
    """Create a new budget alert threshold.

    Rules:
    - threshold_pct must be 1–100 (validated by schema).
    - If scope=cost_center, cost_center_id must be provided and belong to
      the account.
    - No duplicate scope + cost_center_id + threshold_pct per account (409).

    Raises:
        HTTPException 400: cost_center scope missing cost_center_id.
        HTTPException 404: cost_center_id not found or wrong account.
        HTTPException 409: duplicate alert configuration.
    """
    scope = BudgetAlertScope(data.scope)

    cost_center_id: int | None = data.cost_center_id

    if scope == BudgetAlertScope.cost_center:
        if cost_center_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cost_center_id is required when scope is 'cost_center'.",
            )
        # Validate cost center belongs to this account
        await _get_cost_center(db, cost_center_id, account_id)
    else:
        cost_center_id = None

    # Check for duplicate
    dup_result = await db.execute(
        select(CorporateBudgetAlert).where(
            CorporateBudgetAlert.corporate_account_id == account_id,
            CorporateBudgetAlert.scope == scope,
            CorporateBudgetAlert.cost_center_id == cost_center_id,
            CorporateBudgetAlert.threshold_pct == data.threshold_pct,
        )
    )
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A budget alert with the same scope, cost center, and threshold already exists.",
        )

    alert = CorporateBudgetAlert(
        corporate_account_id=account_id,
        scope=scope,
        cost_center_id=cost_center_id,
        threshold_pct=data.threshold_pct,
        label=getattr(data, "label", None),
        status=BudgetAlertStatus.active,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


async def get_budget_alert(
    db: AsyncSession,
    account_id: int,
    alert_id: uuid.UUID,
) -> CorporateBudgetAlert:
    """Return a budget alert by ID, scoped to the account.

    Raises:
        HTTPException 404: Not found or account mismatch.
    """
    return await _get_alert(db, account_id, alert_id)


async def list_budget_alerts(
    db: AsyncSession,
    account_id: int,
    *,
    scope: str | None = None,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[CorporateBudgetAlert], int]:
    """Return budget alerts for an account with optional filters.

    Returns:
        Tuple of (alerts list, total count).
    """
    base_q = select(CorporateBudgetAlert).where(
        CorporateBudgetAlert.corporate_account_id == account_id
    )
    if scope is not None:
        base_q = base_q.where(
            CorporateBudgetAlert.scope == BudgetAlertScope(scope)
        )
    if status_filter is not None:
        base_q = base_q.where(
            CorporateBudgetAlert.status == BudgetAlertStatus(status_filter)
        )

    count_result = await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        base_q.order_by(CorporateBudgetAlert.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    alerts = list(result.scalars().all())
    return alerts, total


async def update_budget_alert(
    db: AsyncSession,
    account_id: int,
    alert_id: uuid.UUID,
    data,
) -> CorporateBudgetAlert:
    """Partial update of a budget alert.

    Only active alerts may be updated.  Triggered or acknowledged alerts are
    immutable (use acknowledge_alert to acknowledge).

    Raises:
        HTTPException 404: Alert not found.
        HTTPException 409: Alert is not in active status.
    """
    alert = await _get_alert(db, account_id, alert_id)

    if alert.status != BudgetAlertStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot update a budget alert with status '{alert.status.value}'. Only active alerts can be updated.",
        )

    if data.label is not None:
        alert.label = data.label
    if data.threshold_pct is not None:
        alert.threshold_pct = data.threshold_pct

    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


async def delete_budget_alert(
    db: AsyncSession,
    account_id: int,
    alert_id: uuid.UUID,
) -> None:
    """Delete a budget alert configuration.

    Raises:
        HTTPException 404: Alert not found.
    """
    alert = await _get_alert(db, account_id, alert_id)
    await db.delete(alert)
    await db.commit()


async def acknowledge_alert(
    db: AsyncSession,
    account_id: int,
    alert_id: uuid.UUID,
    user_id: int,
) -> CorporateBudgetAlert:
    """Transition a triggered alert to acknowledged.

    Raises:
        HTTPException 404: Alert not found.
        HTTPException 409: Alert is not in triggered status.
    """
    alert = await _get_alert(db, account_id, alert_id)

    if alert.status != BudgetAlertStatus.triggered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot acknowledge a budget alert with status '{alert.status.value}'. Only triggered alerts can be acknowledged.",
        )

    alert.status = BudgetAlertStatus.acknowledged
    alert.acknowledged_at = datetime.now(tz=timezone.utc)
    alert.acknowledged_by_id = user_id

    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------


async def evaluate_budget_alerts(
    db: AsyncSession,
    account_id: int,
    billing_month: date,
) -> list[CorporateBudgetAlert]:
    """Evaluate all active alerts for an account and trigger those that qualify.

    For each active alert:
    - cost_center scope: compares cost-center monthly spend vs
      ``CorporateCostCenter.monthly_budget``.
    - account scope: compares total account monthly spend vs
      ``BusinessAccount.monthly_budget_limit``.

    If spend_pct >= threshold_pct, the alert is flipped to triggered and
    spend_at_trigger_usd, budget_at_trigger_usd, billing_month, and
    triggered_at are recorded.

    Alerts already in triggered or acknowledged status are ignored (even if
    the spend is still above threshold).

    Args:
        db: Async database session.
        account_id: The corporate account to evaluate.
        billing_month: The first day of the billing month to evaluate.

    Returns:
        List of newly triggered CorporateBudgetAlert instances.
    """
    # Normalise to first of month
    billing_month = billing_month.replace(day=1)

    # Load account for budget_limit
    account = await _get_account(db, account_id)

    # Fetch all active alerts for this account
    result = await db.execute(
        select(CorporateBudgetAlert).where(
            CorporateBudgetAlert.corporate_account_id == account_id,
            CorporateBudgetAlert.status == BudgetAlertStatus.active,
        )
    )
    active_alerts = list(result.scalars().all())

    if not active_alerts:
        return []

    now = datetime.now(tz=timezone.utc)
    newly_triggered: list[CorporateBudgetAlert] = []

    # Cache per-cost-center spend to avoid redundant queries
    cc_spend_cache: dict[int, Decimal] = {}
    account_spend_cache: Decimal | None = None

    for alert in active_alerts:
        if alert.scope == BudgetAlertScope.cost_center:
            if alert.cost_center_id is None:
                continue

            # Load cost center budget
            cc_result = await db.execute(
                select(CorporateCostCenter).where(
                    CorporateCostCenter.id == alert.cost_center_id
                )
            )
            cc = cc_result.scalar_one_or_none()
            if cc is None or cc.monthly_budget is None or cc.monthly_budget <= 0:
                # No budget configured — skip
                continue

            if alert.cost_center_id not in cc_spend_cache:
                cc_spend_cache[alert.cost_center_id] = await _get_cost_center_spend(
                    db, alert.cost_center_id, billing_month
                )
            spend = cc_spend_cache[alert.cost_center_id]
            budget = Decimal(str(cc.monthly_budget))

        else:
            # account scope
            if account.monthly_budget_limit is None or account.monthly_budget_limit <= 0:
                continue

            if account_spend_cache is None:
                account_spend_cache = await _get_account_spend(
                    db, account_id, billing_month
                )
            spend = account_spend_cache
            budget = Decimal(str(account.monthly_budget_limit))

        spend_pct = (spend / budget) * 100
        if spend_pct >= alert.threshold_pct:
            alert.status = BudgetAlertStatus.triggered
            alert.triggered_at = now
            alert.billing_month = billing_month
            alert.spend_at_trigger_usd = spend.quantize(Decimal("0.01"))
            alert.budget_at_trigger_usd = budget.quantize(Decimal("0.01"))
            db.add(alert)
            newly_triggered.append(alert)

    if newly_triggered:
        await db.commit()
        for alert in newly_triggered:
            await db.refresh(alert)

    return newly_triggered
