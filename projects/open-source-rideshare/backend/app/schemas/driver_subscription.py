"""Pydantic schemas for the driver subscription plan feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_subscription import (
    DriverSubscriptionPlan,
    DriverSubscriptionStatus,
    PLAN_DETAILS,
    STANDARD_COMMISSION_PCT,
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    """Payload to subscribe to a plan."""

    plan: DriverSubscriptionPlan
    auto_renew: bool = True
    stripe_subscription_id: str | None = Field(
        default=None,
        description="Stripe subscription ID — supplied by the client after checkout.",
    )


class UpdateSubscriptionRequest(BaseModel):
    """Update mutable fields on an active subscription."""

    auto_renew: bool


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class PlanDetails(BaseModel):
    """Static definition of a subscription plan."""

    plan: DriverSubscriptionPlan
    label: str
    price: float
    billing_days: int
    commission_pct: float = 0.0

    model_config = {"from_attributes": True}


class DriverSubscriptionResponse(BaseModel):
    """Subscription details returned to the driver."""

    id: int
    driver_id: int
    plan: DriverSubscriptionPlan
    status: DriverSubscriptionStatus
    started_at: datetime
    expires_at: datetime
    price: float
    commission_pct: float
    auto_renew: bool
    stripe_subscription_id: str | None
    cancelled_at: datetime | None

    model_config = {"from_attributes": True}


class AdminDriverSubscriptionResponse(DriverSubscriptionResponse):
    """Extended subscription view for admins (same fields, different auth)."""

    pass


class SubscriptionStatsResponse(BaseModel):
    """Aggregate stats for admin overview."""

    total_active: int
    total_cancelled: int
    total_expired: int
    weekly_active: int
    monthly_active: int
    # Revenue from active subscriptions that haven't expired
    active_revenue_weekly: float
    active_revenue_monthly: float
    active_revenue_total: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_all_plan_details() -> list[PlanDetails]:
    """Return static details for all available plans."""
    return [
        PlanDetails(
            plan=plan,
            label=details["label"],
            price=details["price"],
            billing_days=details["billing_days"],
            commission_pct=0.0,
        )
        for plan, details in PLAN_DETAILS.items()
    ]


def get_standard_commission() -> float:
    return STANDARD_COMMISSION_PCT
