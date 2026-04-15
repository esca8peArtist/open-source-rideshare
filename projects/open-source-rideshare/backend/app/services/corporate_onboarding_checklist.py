"""Service layer for the Corporate Account Onboarding Checklist.

Provides a single read-only, computed function that inspects existing data
across multiple corporate account tables to determine which setup steps an
enterprise account admin has completed.

No database writes are performed; no new tables are required.

Public surface
--------------
get_onboarding_checklist(db, account_id) -> OnboardingChecklistResponse
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember
from app.models.corporate_api_key import CorporateApiKey
from app.models.corporate_billing_settings import (
    CorporateBillingSettings,
    CorporatePaymentMethod,
)
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_notification_settings import CorporateNotificationConfig
from app.models.corporate_ride_policy import CorporateRidePolicy
from app.models.corporate_sso_config import CorporateSSOConfig, SSOStatus
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.models.corporate_webhook import CorporateWebhook
from app.schemas.corporate_onboarding_checklist import (
    OnboardingChecklistResponse,
    OnboardingStep,
)


async def get_onboarding_checklist(
    db: AsyncSession,
    account_id: int,
) -> OnboardingChecklistResponse:
    """Return the computed onboarding checklist for a corporate account.

    Checks eight setup areas — five required and three optional — by running
    lightweight ``SELECT COUNT(*)`` queries against existing tables.  No
    membership or role enforcement is performed here; callers are responsible
    for authorisation.

    Args:
        db:         Async database session.
        account_id: The corporate account to inspect.

    Returns:
        OnboardingChecklistResponse with completion status for every step.
    """
    # ------------------------------------------------------------------
    # Step 1 (required): billing — CorporateBillingSettings row exists
    # AND at least one active CorporatePaymentMethod for this account.
    # ------------------------------------------------------------------
    billing_settings_count: int = await db.scalar(
        select(func.count()).where(
            CorporateBillingSettings.account_id == account_id
        )
    ) or 0

    active_payment_method_count: int = await db.scalar(
        select(func.count()).where(
            CorporatePaymentMethod.account_id == account_id,
            CorporatePaymentMethod.is_active.is_(True),
        )
    ) or 0

    billing_complete = billing_settings_count > 0 and active_payment_method_count > 0

    # ------------------------------------------------------------------
    # Step 2 (required): employees — at least 1 active member.
    # ------------------------------------------------------------------
    member_count: int = await db.scalar(
        select(func.count()).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
        )
    ) or 0

    employees_complete = member_count >= 1

    # ------------------------------------------------------------------
    # Step 3 (required): ride_policy — CorporateRidePolicy row exists.
    # ------------------------------------------------------------------
    ride_policy_count: int = await db.scalar(
        select(func.count()).where(
            CorporateRidePolicy.account_id == account_id
        )
    ) or 0

    ride_policy_complete = ride_policy_count > 0

    # ------------------------------------------------------------------
    # Step 4 (required): cost_centers — at least 1 active cost center.
    # ------------------------------------------------------------------
    cost_center_count: int = await db.scalar(
        select(func.count()).where(
            CorporateCostCenter.account_id == account_id,
            CorporateCostCenter.is_active.is_(True),
        )
    ) or 0

    cost_centers_complete = cost_center_count > 0

    # ------------------------------------------------------------------
    # Step 5 (required): trip_purposes — at least 1 active trip purpose.
    # ------------------------------------------------------------------
    trip_purpose_count: int = await db.scalar(
        select(func.count()).where(
            CorporateTripPurpose.account_id == account_id,
            CorporateTripPurpose.is_active.is_(True),
        )
    ) or 0

    trip_purposes_complete = trip_purpose_count > 0

    # ------------------------------------------------------------------
    # Step 6 (optional): notifications — at least 1 enabled config row.
    # ------------------------------------------------------------------
    notification_count: int = await db.scalar(
        select(func.count()).where(
            CorporateNotificationConfig.account_id == account_id,
            CorporateNotificationConfig.enabled.is_(True),
        )
    ) or 0

    notifications_complete = notification_count > 0

    # ------------------------------------------------------------------
    # Step 7 (optional): sso — active CorporateSSOConfig row.
    # ------------------------------------------------------------------
    sso_count: int = await db.scalar(
        select(func.count()).where(
            CorporateSSOConfig.account_id == account_id,
            CorporateSSOConfig.status == SSOStatus.active,
        )
    ) or 0

    sso_complete = sso_count > 0

    # ------------------------------------------------------------------
    # Step 8 (optional): integrations — active webhook OR active API key.
    # ------------------------------------------------------------------
    webhook_count: int = await db.scalar(
        select(func.count()).where(
            CorporateWebhook.account_id == account_id,
            CorporateWebhook.is_active.is_(True),
        )
    ) or 0

    api_key_count: int = await db.scalar(
        select(func.count()).where(
            CorporateApiKey.account_id == account_id,
            CorporateApiKey.is_active.is_(True),
        )
    ) or 0

    integrations_complete = (webhook_count > 0) or (api_key_count > 0)

    # ------------------------------------------------------------------
    # Build the ordered step list (required first, optional last).
    # ------------------------------------------------------------------
    steps: list[OnboardingStep] = [
        OnboardingStep(
            step_key="billing",
            title="Billing Setup",
            description=(
                "Configure billing settings and add at least one active payment method."
            ),
            is_complete=billing_complete,
            is_optional=False,
            action_hint="/corporate/billing",
        ),
        OnboardingStep(
            step_key="employees",
            title="Add Employees",
            description="Invite or add at least one active employee member to the account.",
            is_complete=employees_complete,
            is_optional=False,
            action_hint="/corporate/employees",
        ),
        OnboardingStep(
            step_key="ride_policy",
            title="Ride Policy",
            description="Define a ride policy to govern which rides employees may book.",
            is_complete=ride_policy_complete,
            is_optional=False,
            action_hint="/corporate/ride-policy",
        ),
        OnboardingStep(
            step_key="cost_centers",
            title="Cost Centers",
            description="Create at least one active cost center for expense tracking.",
            is_complete=cost_centers_complete,
            is_optional=False,
            action_hint="/corporate/cost-centers",
        ),
        OnboardingStep(
            step_key="trip_purposes",
            title="Trip Purposes",
            description="Define at least one active trip purpose code for ride tagging.",
            is_complete=trip_purposes_complete,
            is_optional=False,
            action_hint="/corporate/trip-purposes",
        ),
        OnboardingStep(
            step_key="notifications",
            title="Notification Settings",
            description="Enable at least one notification event to stay informed.",
            is_complete=notifications_complete,
            is_optional=True,
            action_hint="/corporate/notifications",
        ),
        OnboardingStep(
            step_key="sso",
            title="Single Sign-On (SSO)",
            description="Configure and activate SSO so employees log in via your identity provider.",
            is_complete=sso_complete,
            is_optional=True,
            action_hint="/corporate/sso",
        ),
        OnboardingStep(
            step_key="integrations",
            title="Integrations",
            description="Connect an active webhook or API key to integrate with your systems.",
            is_complete=integrations_complete,
            is_optional=True,
            action_hint="/corporate/integrations",
        ),
    ]

    required_steps = [s for s in steps if not s.is_optional]
    optional_steps = [s for s in steps if s.is_optional]

    total_steps = len(steps)
    n_required = len(required_steps)
    completed_required = sum(1 for s in required_steps if s.is_complete)
    completed_optional = sum(1 for s in optional_steps if s.is_complete)
    all_required_complete = completed_required == n_required
    completion_pct = (completed_required / n_required * 100) if n_required > 0 else 0.0

    return OnboardingChecklistResponse(
        account_id=account_id,
        total_steps=total_steps,
        required_steps=n_required,
        completed_required=completed_required,
        completed_optional=completed_optional,
        all_required_complete=all_required_complete,
        completion_pct=completion_pct,
        steps=steps,
    )
