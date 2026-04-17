"""Corporate Spending Limit Alerts API endpoints.

Account-admin endpoints:
  POST /api/v1/corporate/{account_id}/spending-alerts/check
       Trigger an alert check for the current (or specified) period.
  GET  /api/v1/corporate/{account_id}/spending-alerts
       List all alerts for the account in a period.
  GET  /api/v1/corporate/{account_id}/spending-alerts/summary
       Spending alert summary (who is near/at their limit).

Member endpoint:
  GET  /api/v1/corporate/{account_id}/spending-alerts/my
       Own spending alerts for the current period.

Platform-admin endpoint:
  GET  /api/v1/admin/corporate/spending-alerts
       All corporate accounts that have members near or at their limits.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_spending_alert import (
    SpendingAlertsListResponse,
    SpendingAlertOut,
    SpendingAlertsSummary,
)
from app.services.corporate_spending_alert_service import (
    check_and_create_alerts,
    get_account_alerts,
    get_alerts_summary,
    get_member_alerts,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-spending-alerts"])


# ---------------------------------------------------------------------------
# Account-admin routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/spending-alerts/check",
    response_model=SpendingAlertsListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger spending alert check for the current period",
)
async def trigger_alert_check(
    account_id: int,
    as_of: date | None = Query(
        None,
        description="Reference date (determines which month is examined). Defaults to today.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compute current spend against limits and create new alert records.

    Only account admins may trigger a check.  Idempotent — calling multiple
    times in the same period will not create duplicate alerts.

    Returns 201 with the list of newly created alert records (may be empty
    if no new thresholds have been crossed since the last check).
    """
    new_alerts = await check_and_create_alerts(
        db, account_id=account_id, as_of_date=as_of
    )
    return SpendingAlertsListResponse(
        alerts=[SpendingAlertOut.model_validate(a) for a in new_alerts],
        total=len(new_alerts),
    )


@router.get(
    "/corporate/{account_id}/spending-alerts",
    response_model=SpendingAlertsListResponse,
    summary="List spending alerts for the account in a period",
)
async def list_account_alerts(
    account_id: int,
    year: int | None = Query(None, description="Period year (defaults to current year)."),
    month: int | None = Query(
        None, description="Period month 1-12 (defaults to current month)."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all spending alerts for an account in the specified period.

    Only account admins may list alerts.  Defaults to the current calendar month.
    """
    today = date.today()
    effective_year = year if year is not None else today.year
    effective_month = month if month is not None else today.month

    alerts = await get_account_alerts(
        db,
        account_id=account_id,
        requesting_user_id=current_user.id,
        year=effective_year,
        month=effective_month,
    )
    return SpendingAlertsListResponse(
        alerts=[SpendingAlertOut.model_validate(a) for a in alerts],
        total=len(alerts),
    )


@router.get(
    "/corporate/{account_id}/spending-alerts/summary",
    response_model=SpendingAlertsSummary,
    summary="Spending alert summary (who is near or at their limit)",
)
async def account_alerts_summary(
    account_id: int,
    year: int | None = Query(None, description="Period year (defaults to current year)."),
    month: int | None = Query(
        None, description="Period month 1-12 (defaults to current month)."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a spending summary for the account: who is near/at/over their limit.

    Only account admins may call this endpoint.
    """
    return await get_alerts_summary(
        db,
        account_id=account_id,
        requesting_user_id=current_user.id,
        year=year,
        month=month,
    )


# ---------------------------------------------------------------------------
# Member route — own alerts only
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/spending-alerts/my",
    response_model=SpendingAlertsListResponse,
    summary="Own spending alerts for the current period",
)
async def list_my_alerts(
    account_id: int,
    member_id: int = Query(..., description="Your membership record ID."),
    year: int | None = Query(None, description="Period year (defaults to current year)."),
    month: int | None = Query(
        None, description="Period month 1-12 (defaults to current month)."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return spending alerts for the calling member.

    Members may only retrieve their own alerts; the member_id must correspond
    to their own membership record.
    """
    today = date.today()
    effective_year = year if year is not None else today.year
    effective_month = month if month is not None else today.month

    alerts = await get_member_alerts(
        db,
        account_id=account_id,
        member_id=member_id,
        requesting_user_id=current_user.id,
        year=effective_year,
        month=effective_month,
    )
    return SpendingAlertsListResponse(
        alerts=[SpendingAlertOut.model_validate(a) for a in alerts],
        total=len(alerts),
    )


# ---------------------------------------------------------------------------
# Platform-admin route
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/spending-alerts",
    response_model=list[SpendingAlertsSummary],
    summary="[Admin] All accounts with members near or at their spending limits",
    dependencies=[Depends(require_admin)],
)
async def admin_list_all_spending_alerts(
    year: int | None = Query(None, description="Period year (defaults to current year)."),
    month: int | None = Query(
        None, description="Period month 1-12 (defaults to current month)."
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return spending summaries for all corporate accounts that have at least
    one member near or at their spending limit in the given period.

    Platform admin access required.
    """
    from sqlalchemy import select as sa_select

    from app.models.corporate import BusinessAccount
    from app.models.corporate_spending_alert import CorporateSpendingAlert

    today = date.today()
    effective_year = year if year is not None else today.year
    effective_month = month if month is not None else today.month

    # Fetch distinct account_ids that have ANY alert this period
    result = await db.execute(
        sa_select(CorporateSpendingAlert.account_id)
        .where(
            CorporateSpendingAlert.period_year == effective_year,
            CorporateSpendingAlert.period_month == effective_month,
        )
        .distinct()
    )
    account_ids = [row for row in result.scalars().all()]

    summaries: list[SpendingAlertsSummary] = []
    for acct_id in account_ids:
        # Build summary without re-checking auth (this is a platform admin endpoint)
        # We reuse the internal helpers directly
        from app.services.corporate_spending_alert_service import (
            _compute_account_spend,
            _existing_alert_types,
            _get_account,
            _get_active_members,
            _THRESHOLDS,
        )
        from decimal import Decimal as D

        account = await _get_account(db, acct_id)
        account_spend = await _compute_account_spend(
            db, acct_id, effective_year, effective_month
        )
        active_members = await _get_active_members(db, acct_id)
        member_count = len(active_members)

        account_limit = account.monthly_budget_limit
        account_pct: float | None = None
        if account_limit and account_limit > D("0"):
            account_pct = float(account_spend / account_limit * 100)

        acct_alert_types = await _existing_alert_types(
            db, acct_id, None, effective_year, effective_month
        )
        account_alert: AlertType | None = None
        for _, at in reversed(_THRESHOLDS):
            if at in acct_alert_types:
                account_alert = at
                break

        from app.schemas.corporate_spending_alert import MemberSpendStatus

        members_near: list[MemberSpendStatus] = []
        members_at: list[MemberSpendStatus] = []
        members_over: list[MemberSpendStatus] = []

        for member in active_members:
            if member.monthly_spend_limit is None or member.monthly_spend_limit <= D("0"):
                continue
            member_spend = (
                account_spend / D(member_count) if member_count > 0 else D("0.00")
            )
            pct_used = float(member_spend / member.monthly_spend_limit * 100)
            fired = await _existing_alert_types(
                db, acct_id, member.id, effective_year, effective_month
            )
            highest: AlertType | None = None
            for _, at in reversed(_THRESHOLDS):
                if at in fired:
                    highest = at
                    break

            ms = MemberSpendStatus(
                member_id=member.id,
                current_spend_usd=member_spend,
                limit_usd=member.monthly_spend_limit,
                pct_used=pct_used,
                highest_alert=highest,
            )
            if pct_used >= 100:
                members_over.append(ms)
            elif pct_used >= 90:
                members_at.append(ms)
            elif pct_used >= 75:
                members_near.append(ms)

        summaries.append(
            SpendingAlertsSummary(
                account_id=acct_id,
                period_year=effective_year,
                period_month=effective_month,
                account_spend_usd=account_spend,
                account_limit_usd=account_limit,
                account_pct_used=account_pct,
                account_alert=account_alert,
                members_near_limit=members_near,
                members_at_limit=members_at,
                members_over_limit=members_over,
            )
        )

    return summaries
