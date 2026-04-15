"""Schemas for the Corporate Account Dashboard endpoint.

The dashboard returns a single aggregated view of a corporate account's
health — suitable for populating an admin overview page without requiring
multiple separate API calls.

Sections
--------
AccountOverview      — core account fields (name, status, limits)
MembersSummary       — active/admin member counts + pending invitations
SpendSummary         — current-month rides and spend vs budget
CreditSummary        — prepaid credit balance (absent when not configured)
PendingItems         — items waiting for admin action
SetupHealth          — which integrations are configured
AlertsSummary        — active and triggered budget alerts
BlackoutsSummary     — active blackout periods
CorporateAccountDashboard — top-level container
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AccountOverview(BaseModel):
    """Core account fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    billing_email: str
    tax_id: str | None
    monthly_budget_limit: Decimal | None
    created_at: datetime


class MembersSummary(BaseModel):
    """Headcount at a glance."""

    total_active: int
    """Number of members with is_active=True."""

    total_admins: int
    """Active members whose role is 'admin'."""

    pending_invitations: int
    """Invitations with status='pending' (not yet accepted or expired)."""


class SpendSummary(BaseModel):
    """Current-month spending snapshot."""

    rides_this_month: int
    """Completed rides charged to this account in the current calendar month."""

    spend_this_month_usd: Decimal
    """Total fare amount for completed corporate rides this month."""

    monthly_budget_limit: Decimal | None
    """Monthly cap in USD; None if unlimited."""

    budget_utilization_pct: float | None
    """spend_this_month / monthly_budget_limit × 100; None when no limit is set."""


class CreditSummary(BaseModel):
    """Prepaid credit account — only present when a credit account exists."""

    balance_usd: Decimal
    total_deposited_usd: Decimal
    total_spent_usd: Decimal
    low_balance_threshold_usd: Decimal | None
    is_low_balance: bool
    """True when balance ≤ low_balance_threshold_usd (and threshold is set)."""


class PendingItems(BaseModel):
    """Items waiting for admin action."""

    pending_ride_approvals: int
    """Ride approval requests with status='pending'."""

    pending_invitations: int
    """Employee invitations with status='pending'."""


class SetupHealth(BaseModel):
    """Integration configuration status."""

    sso_configured: bool
    """True when a CorporateSSOConfig row exists."""

    sso_status: str | None
    """'pending' | 'active' | 'disabled' — None when sso_configured is False."""

    sso_enforced: bool
    """True when SSO enforcement is active."""

    active_webhooks: int
    """Count of webhooks with is_active=True."""

    active_api_keys: int
    """Count of API keys with is_active=True."""

    billing_contacts: int
    """Count of active billing contacts."""

    account_contacts: int
    """Count of active account contacts (non-billing operational contacts)."""

    notification_configs: int
    """Number of notification event types that have been explicitly configured.
    Max 12 (one per NotificationEventType value)."""


class AlertsSummary(BaseModel):
    """Budget alert state."""

    total_active: int
    """Alerts in 'active' status (threshold not yet crossed)."""

    total_triggered: int
    """Alerts in 'triggered' status (threshold crossed, awaiting acknowledgement)."""


class BlackoutsSummary(BaseModel):
    """Active booking blackout periods."""

    total_active: int
    """Blackout periods with is_active=True."""


class CorporateAccountDashboard(BaseModel):
    """Aggregated health snapshot for a corporate account.

    One call replaces ~10 separate queries when rendering an admin dashboard.
    """

    account: AccountOverview
    members: MembersSummary
    spend: SpendSummary
    credit: CreditSummary | None
    """None when the account has not set up prepaid credits."""

    pending: PendingItems
    setup: SetupHealth
    alerts: AlertsSummary
    blackouts: BlackoutsSummary
    generated_at: datetime
    """Server timestamp when the dashboard was assembled."""
