"""Schemas for rider membership endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.rider_membership import MembershipPlan, MembershipStatus


class PlanDetails(BaseModel):
    """Static description of a membership plan (returned by the plans listing)."""

    plan: MembershipPlan
    monthly_price: float
    fare_discount_pct: float
    surge_cap_multiplier: float
    priority_matching: bool
    description: str


class RiderMembershipSubscribeRequest(BaseModel):
    """Body for subscribing to a membership plan."""

    plan: MembershipPlan


class RiderMembershipResponse(BaseModel):
    """Full membership state returned to the rider."""

    id: int
    rider_id: int
    plan: MembershipPlan
    status: MembershipStatus

    started_at: datetime
    expires_at: datetime

    monthly_price: float
    fare_discount_pct: float
    surge_cap_multiplier: float
    priority_matching: bool

    cancelled_at: datetime | None = None

    # Convenience: is the membership currently granting benefits?
    benefits_active: bool

    model_config = {"from_attributes": True}


class RiderMembershipCancelResponse(BaseModel):
    """Returned by DELETE /riders/me/membership."""

    cancelled: bool
    message: str
    benefits_valid_until: datetime | None = None


class AdminMembershipSummary(BaseModel):
    """Admin overview of all memberships."""

    total_active: int
    basic_active: int
    premium_active: int
    total_cancelled_this_month: int
    monthly_revenue_estimate: float
