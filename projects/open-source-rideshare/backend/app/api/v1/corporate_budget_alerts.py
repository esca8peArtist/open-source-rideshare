"""Corporate Budget Alerts API endpoints.

Admins configure percentage-based alert thresholds on cost centers or the
overall account.  When spend for a billing cycle crosses the threshold an
alert is triggered and surfaced here.

Member endpoints (account admin required):
  POST   /corporate/accounts/me/budget-alerts            — create
  GET    /corporate/accounts/me/budget-alerts            — list (scope, status filters)
  GET    /corporate/accounts/me/budget-alerts/{alert_id} — get one
  PATCH  /corporate/accounts/me/budget-alerts/{alert_id} — update
  DELETE /corporate/accounts/me/budget-alerts/{alert_id} — delete
  POST   /corporate/accounts/me/budget-alerts/{alert_id}/acknowledge — acknowledge
  POST   /corporate/accounts/me/budget-alerts/evaluate   — run evaluation

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/budget-alerts          — list
  POST   /admin/corporate/accounts/{account_id}/budget-alerts/evaluate — trigger evaluation
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_budget_alert import (
    BudgetAlertCreate,
    BudgetAlertListResponse,
    BudgetAlertResponse,
    BudgetAlertUpdate,
    EvaluateAlertsRequest,
    EvaluateAlertsResponse,
)
from app.services.corporate_budget_alert import (
    acknowledge_alert,
    create_budget_alert,
    delete_budget_alert,
    evaluate_budget_alerts,
    get_budget_alert,
    list_budget_alerts,
    update_budget_alert,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-budget-alerts"])


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


def _to_response(alert) -> BudgetAlertResponse:
    """Build a BudgetAlertResponse, injecting cost center fields if present."""
    cost_center_code = None
    cost_center_name = None
    if hasattr(alert, "cost_center") and alert.cost_center is not None:
        cost_center_code = alert.cost_center.code
        cost_center_name = alert.cost_center.name

    return BudgetAlertResponse(
        id=alert.id,
        corporate_account_id=alert.corporate_account_id,
        scope=alert.scope,
        cost_center_id=alert.cost_center_id,
        cost_center_code=cost_center_code,
        cost_center_name=cost_center_name,
        threshold_pct=alert.threshold_pct,
        label=alert.label,
        status=alert.status,
        triggered_at=alert.triggered_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by_id=alert.acknowledged_by_id,
        billing_month=alert.billing_month,
        spend_at_trigger_usd=alert.spend_at_trigger_usd,
        budget_at_trigger_usd=alert.budget_at_trigger_usd,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/budget-alerts",
    response_model=BudgetAlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a budget alert threshold for your corporate account",
)
async def create_my_budget_alert(
    data: BudgetAlertCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new percentage-based budget alert for the caller's account.

    Triggers when spend reaches the configured percentage of the budget.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    alert = await create_budget_alert(db, account_id, data)
    return _to_response(alert)


@router.get(
    "/corporate/accounts/me/budget-alerts",
    response_model=BudgetAlertListResponse,
    summary="List budget alerts for your corporate account",
)
async def list_my_budget_alerts(
    scope: str | None = Query(None, description="Filter by scope: 'cost_center' or 'account'."),
    alert_status: str | None = Query(None, alias="status", description="Filter by status: 'active', 'triggered', 'acknowledged'."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all budget alert thresholds for the caller's corporate account."""
    account_id = await _get_member_account_id(db, current_user.id)
    alerts, total = await list_budget_alerts(
        db, account_id, scope=scope, status_filter=alert_status, skip=skip, limit=limit
    )
    return BudgetAlertListResponse(
        items=[_to_response(a) for a in alerts],
        total=total,
    )


@router.get(
    "/corporate/accounts/me/budget-alerts/{alert_id}",
    response_model=BudgetAlertResponse,
    summary="Get a specific budget alert",
)
async def get_my_budget_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single budget alert by ID, scoped to the caller's account."""
    account_id = await _get_member_account_id(db, current_user.id)
    alert = await get_budget_alert(db, account_id, alert_id)
    return _to_response(alert)


@router.patch(
    "/corporate/accounts/me/budget-alerts/{alert_id}",
    response_model=BudgetAlertResponse,
    summary="Update a budget alert threshold",
)
async def update_my_budget_alert(
    alert_id: uuid.UUID,
    data: BudgetAlertUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update a budget alert.  Only active alerts may be updated."""
    account_id = await _get_member_account_id(db, current_user.id)
    alert = await update_budget_alert(db, account_id, alert_id, data)
    return _to_response(alert)


@router.delete(
    "/corporate/accounts/me/budget-alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a budget alert threshold",
)
async def delete_my_budget_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a budget alert configuration."""
    account_id = await _get_member_account_id(db, current_user.id)
    await delete_budget_alert(db, account_id, alert_id)


@router.post(
    "/corporate/accounts/me/budget-alerts/{alert_id}/acknowledge",
    response_model=BudgetAlertResponse,
    summary="Acknowledge a triggered budget alert",
)
async def acknowledge_my_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Acknowledge a triggered alert, marking it as reviewed."""
    account_id = await _get_member_account_id(db, current_user.id)
    alert = await acknowledge_alert(db, account_id, alert_id, current_user.id)
    return _to_response(alert)


@router.post(
    "/corporate/accounts/me/budget-alerts/evaluate",
    response_model=EvaluateAlertsResponse,
    summary="Evaluate budget alerts for a billing month",
)
async def evaluate_my_budget_alerts(
    data: EvaluateAlertsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run the evaluation engine for a given billing month.

    Checks all active alerts against current spend and triggers those that
    have crossed their threshold.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    triggered = await evaluate_budget_alerts(db, account_id, data.billing_month)
    return EvaluateAlertsResponse(
        triggered_count=len(triggered),
        triggered_alerts=[_to_response(a) for a in triggered],
    )


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/budget-alerts",
    response_model=BudgetAlertListResponse,
    summary="[Admin] List budget alerts for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_budget_alerts(
    account_id: int,
    scope: str | None = Query(None),
    alert_status: str | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List budget alerts for any corporate account (platform admin only)."""
    alerts, total = await list_budget_alerts(
        db, account_id, scope=scope, status_filter=alert_status, skip=skip, limit=limit
    )
    return BudgetAlertListResponse(
        items=[_to_response(a) for a in alerts],
        total=total,
    )


@router.post(
    "/admin/corporate/accounts/{account_id}/budget-alerts/evaluate",
    response_model=EvaluateAlertsResponse,
    summary="[Admin] Trigger budget alert evaluation for any account",
    dependencies=[Depends(require_admin)],
)
async def admin_evaluate_budget_alerts(
    account_id: int,
    data: EvaluateAlertsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run budget alert evaluation for any account (platform admin only)."""
    triggered = await evaluate_budget_alerts(db, account_id, data.billing_month)
    return EvaluateAlertsResponse(
        triggered_count=len(triggered),
        triggered_alerts=[_to_response(a) for a in triggered],
    )
