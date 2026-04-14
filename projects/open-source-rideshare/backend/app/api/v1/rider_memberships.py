"""Rider membership API endpoints.

Rider-facing:
  GET    /riders/me/membership/plans   — list available plans with pricing
  POST   /riders/me/membership         — subscribe to a plan
  GET    /riders/me/membership         — get current membership status
  DELETE /riders/me/membership         — cancel active membership

Admin:
  GET    /admin/memberships            — aggregate stats (counts, revenue)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.rider_membership import (
    AdminMembershipSummary,
    PlanDetails,
    RiderMembershipCancelResponse,
    RiderMembershipResponse,
    RiderMembershipSubscribeRequest,
)
from app.services.rider_membership import (
    benefits_active,
    cancel_membership,
    get_active_membership,
    get_admin_summary,
    get_all_plans,
    subscribe,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-memberships"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _to_response(membership) -> RiderMembershipResponse:
    return RiderMembershipResponse(
        id=membership.id,
        rider_id=membership.rider_id,
        plan=membership.plan,
        status=membership.status,
        started_at=membership.started_at,
        expires_at=membership.expires_at,
        monthly_price=membership.monthly_price,
        fare_discount_pct=membership.fare_discount_pct,
        surge_cap_multiplier=membership.surge_cap_multiplier,
        priority_matching=membership.priority_matching,
        cancelled_at=membership.cancelled_at,
        benefits_active=benefits_active(membership),
    )


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/membership/plans",
    response_model=list[PlanDetails],
    summary="List available membership plans",
)
async def list_plans():
    """Return all available membership plans with their pricing and benefits.

    No authentication required — anyone can browse plans.
    """
    return get_all_plans()


@router.post(
    "/riders/me/membership",
    response_model=RiderMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a membership plan",
)
async def create_membership(
    req: RiderMembershipSubscribeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subscribe the authenticated rider to a membership plan.

    If the rider is already on this plan, the existing membership is returned
    unchanged (idempotent).  If the rider is on a different plan, the old plan
    is cancelled immediately and a new 30-day billing period starts.

    **Benefits applied at ride booking**: fare discount and surge cap are
    applied automatically — no action needed at booking time.
    """
    membership = await subscribe(db, user.id, req.plan)
    return _to_response(membership)


@router.get(
    "/riders/me/membership",
    response_model=RiderMembershipResponse,
    summary="Get current membership status",
)
async def get_membership(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the rider's current membership (active or recently cancelled).

    Returns **404** if the rider has no membership or their last membership
    has fully expired.
    """
    membership = await get_active_membership(db, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active membership found.",
        )
    return _to_response(membership)


@router.delete(
    "/riders/me/membership",
    response_model=RiderMembershipCancelResponse,
    summary="Cancel the active membership",
)
async def delete_membership(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel the rider's membership.

    Benefits remain valid until the end of the current billing period
    (`expires_at`).  No refund is issued for the remaining days.

    Returns **404** if there is no active membership to cancel.
    """
    membership = await cancel_membership(db, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active membership to cancel.",
        )
    return RiderMembershipCancelResponse(
        cancelled=True,
        message=(
            f"Membership cancelled. Your {membership.plan.value} benefits "
            f"remain active until {membership.expires_at.date()}."
        ),
        benefits_valid_until=membership.expires_at,
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/memberships",
    response_model=AdminMembershipSummary,
    summary="Admin: membership aggregate statistics",
)
async def admin_membership_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate membership statistics.

    Requires admin role.  Returns total active counts by plan,
    cancellations this month, and estimated monthly recurring revenue.
    """
    if not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    summary = await get_admin_summary(db)
    return AdminMembershipSummary(**summary)
