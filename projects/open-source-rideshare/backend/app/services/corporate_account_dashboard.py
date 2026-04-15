"""Service function for the Corporate Account Dashboard.

Aggregates data from multiple corporate tables into a single snapshot.
No writes are performed; all queries are read-only.

Public API
----------
get_account_dashboard   — return the full dashboard dict for one account
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount, BusinessAccountMember, MemberRole
from app.models.corporate_account_contact import CorporateAccountContact
from app.models.corporate_api_key import CorporateApiKey
from app.models.corporate_billing_contact import CorporateBillingContact
from app.models.corporate_blackout_period import CorporateBlackoutPeriod
from app.models.corporate_budget_alert import BudgetAlertStatus, CorporateBudgetAlert
from app.models.corporate_credit_account import CorporateCreditAccount
from app.models.corporate_employee_invitation import (
    CorporateEmployeeInvitation,
    InvitationStatus,
)
from app.models.corporate_notification_settings import CorporateNotificationConfig
from app.models.corporate_ride_approval import ApprovalStatus, CorporateRideApproval
from app.models.corporate_sso_config import CorporateSSOConfig
from app.models.corporate_webhook import CorporateWebhook
from app.models.ride import Ride


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def get_account_dashboard(
    db: AsyncSession,
    account_id: int,
) -> dict:
    """Return the full dashboard snapshot for *account_id*.

    Raises 404 when the account does not exist.

    Returns a dict matching the CorporateAccountDashboard schema.
    """
    # 1. Account overview — raises 404 if missing
    account = await _get_account_or_404(db, account_id)

    # Parallel sub-queries (all independent)
    (
        active_members,
        admin_members,
        pending_invitations,
        pending_approvals,
        sso_config,
        active_webhooks,
        active_api_keys,
        billing_contacts,
        account_contacts,
        notification_configs,
        active_blackouts,
        active_alerts,
        triggered_alerts,
        credit_account,
        rides_this_month,
        spend_this_month,
    ) = await _run_sub_queries(db, account_id)

    now = datetime.now(tz=timezone.utc)
    month_key = now.strftime("%Y-%m")

    # Build spend summary
    budget = account.monthly_budget_limit
    utilization: float | None = None
    if budget is not None and budget > 0:
        utilization = round(float(spend_this_month) / float(budget) * 100, 2)

    # Build credit summary (None when no credit account)
    credit_section = None
    if credit_account is not None:
        threshold = credit_account.low_balance_threshold_usd
        is_low = (
            threshold is not None
            and credit_account.balance_usd <= threshold
        )
        credit_section = {
            "balance_usd": credit_account.balance_usd,
            "total_deposited_usd": credit_account.total_deposited_usd,
            "total_spent_usd": credit_account.total_spent_usd,
            "low_balance_threshold_usd": threshold,
            "is_low_balance": is_low,
        }

    # Build SSO section
    sso_configured = sso_config is not None
    sso_status = sso_config.status.value if sso_config else None
    sso_enforced = bool(sso_config and sso_config.enforce_sso)

    return {
        "account": {
            "id": account.id,
            "name": account.name,
            "status": account.status.value,
            "billing_email": account.billing_email,
            "tax_id": account.tax_id,
            "monthly_budget_limit": account.monthly_budget_limit,
            "created_at": account.created_at,
        },
        "members": {
            "total_active": active_members,
            "total_admins": admin_members,
            "pending_invitations": pending_invitations,
        },
        "spend": {
            "rides_this_month": rides_this_month,
            "spend_this_month_usd": spend_this_month,
            "monthly_budget_limit": account.monthly_budget_limit,
            "budget_utilization_pct": utilization,
        },
        "credit": credit_section,
        "pending": {
            "pending_ride_approvals": pending_approvals,
            "pending_invitations": pending_invitations,
        },
        "setup": {
            "sso_configured": sso_configured,
            "sso_status": sso_status,
            "sso_enforced": sso_enforced,
            "active_webhooks": active_webhooks,
            "active_api_keys": active_api_keys,
            "billing_contacts": billing_contacts,
            "account_contacts": account_contacts,
            "notification_configs": notification_configs,
        },
        "alerts": {
            "total_active": active_alerts,
            "total_triggered": triggered_alerts,
        },
        "blackouts": {
            "total_active": active_blackouts,
        },
        "generated_at": now,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_account_or_404(
    db: AsyncSession, account_id: int
) -> BusinessAccount:
    result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Corporate account {account_id} not found.",
        )
    return account


async def _count(db: AsyncSession, stmt) -> int:
    """Execute a scalar count query and return the integer result."""
    result = await db.execute(stmt)
    value = result.scalar_one_or_none()
    return int(value) if value is not None else 0


async def _run_sub_queries(
    db: AsyncSession, account_id: int
) -> tuple:
    """Execute all dashboard sub-queries and return a flat tuple of values."""
    now = datetime.now(tz=timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Active members
    active_members = await _count(
        db,
        select(func.count(BusinessAccountMember.id)).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
        ),
    )

    # Admin members (active)
    admin_members = await _count(
        db,
        select(func.count(BusinessAccountMember.id)).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
            BusinessAccountMember.role == MemberRole.ADMIN,
        ),
    )

    # Pending invitations
    pending_invitations = await _count(
        db,
        select(func.count(CorporateEmployeeInvitation.id)).where(
            CorporateEmployeeInvitation.account_id == account_id,
            CorporateEmployeeInvitation.status == InvitationStatus.PENDING,
        ),
    )

    # Pending ride approvals
    pending_approvals = await _count(
        db,
        select(func.count(CorporateRideApproval.id)).where(
            CorporateRideApproval.account_id == account_id,
            CorporateRideApproval.status == ApprovalStatus.PENDING,
        ),
    )

    # SSO config (single row per account)
    sso_result = await db.execute(
        select(CorporateSSOConfig).where(
            CorporateSSOConfig.account_id == account_id
        )
    )
    sso_config = sso_result.scalar_one_or_none()

    # Active webhooks
    active_webhooks = await _count(
        db,
        select(func.count(CorporateWebhook.id)).where(
            CorporateWebhook.account_id == account_id,
            CorporateWebhook.is_active.is_(True),
        ),
    )

    # Active API keys
    active_api_keys = await _count(
        db,
        select(func.count(CorporateApiKey.id)).where(
            CorporateApiKey.account_id == account_id,
            CorporateApiKey.is_active.is_(True),
        ),
    )

    # Billing contacts (active)
    billing_contacts = await _count(
        db,
        select(func.count(CorporateBillingContact.id)).where(
            CorporateBillingContact.account_id == account_id,
            CorporateBillingContact.is_active.is_(True),
        ),
    )

    # Account contacts (active)
    account_contacts = await _count(
        db,
        select(func.count(CorporateAccountContact.id)).where(
            CorporateAccountContact.account_id == account_id,
            CorporateAccountContact.is_active.is_(True),
        ),
    )

    # Notification configs (explicitly created rows)
    notification_configs = await _count(
        db,
        select(func.count(CorporateNotificationConfig.id)).where(
            CorporateNotificationConfig.account_id == account_id,
        ),
    )

    # Active blackout periods
    active_blackouts = await _count(
        db,
        select(func.count(CorporateBlackoutPeriod.id)).where(
            CorporateBlackoutPeriod.account_id == account_id,
            CorporateBlackoutPeriod.is_active.is_(True),
        ),
    )

    # Budget alerts — active status (threshold not yet crossed)
    active_alerts = await _count(
        db,
        select(func.count(CorporateBudgetAlert.id)).where(
            CorporateBudgetAlert.account_id == account_id,
            CorporateBudgetAlert.status == BudgetAlertStatus.active,
        ),
    )

    # Budget alerts — triggered status (awaiting acknowledgement)
    triggered_alerts = await _count(
        db,
        select(func.count(CorporateBudgetAlert.id)).where(
            CorporateBudgetAlert.account_id == account_id,
            CorporateBudgetAlert.status == BudgetAlertStatus.triggered,
        ),
    )

    # Credit account (may not exist)
    credit_result = await db.execute(
        select(CorporateCreditAccount).where(
            CorporateCreditAccount.account_id == account_id
        )
    )
    credit_account = credit_result.scalar_one_or_none()

    # Current-month ride count (completed rides charged to this account)
    rides_this_month = await _count(
        db,
        select(func.count(Ride.id)).where(
            Ride.corporate_account_id == account_id,
            Ride.status == "completed",
            Ride.created_at >= month_start,
        ),
    )

    # Current-month spend (sum of actual_fare for completed rides)
    spend_result = await db.execute(
        select(func.coalesce(func.sum(Ride.actual_fare), Decimal("0.00"))).where(
            Ride.corporate_account_id == account_id,
            Ride.status == "completed",
            Ride.created_at >= month_start,
        )
    )
    spend_this_month = spend_result.scalar_one() or Decimal("0.00")

    return (
        active_members,
        admin_members,
        pending_invitations,
        pending_approvals,
        sso_config,
        active_webhooks,
        active_api_keys,
        billing_contacts,
        account_contacts,
        notification_configs,
        active_blackouts,
        active_alerts,
        triggered_alerts,
        credit_account,
        rides_this_month,
        spend_this_month,
    )
