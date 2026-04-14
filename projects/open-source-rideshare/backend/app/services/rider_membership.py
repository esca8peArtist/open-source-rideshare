"""Rider membership service.

Handles subscription, cancellation, and benefit application for rider
membership plans (analogous to Uber One / Lyft Pink).

Plan catalogue
--------------
basic   — $9.99/mo  — 10% fare discount, surge capped at 2.0×
premium — $19.99/mo — 20% fare discount, surge capped at 1.5×, priority match

Pure helpers (plan_benefits, apply_membership_discount, apply_surge_cap,
benefits_active) contain no I/O and are fully unit-testable.
Async functions handle DB operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rider_membership import MembershipPlan, MembershipStatus, RiderMembership
from app.schemas.rider_membership import PlanDetails


# ---------------------------------------------------------------------------
# Plan catalogue — single source of truth
# ---------------------------------------------------------------------------

_PLAN_CATALOGUE: dict[MembershipPlan, PlanDetails] = {
    MembershipPlan.basic: PlanDetails(
        plan=MembershipPlan.basic,
        monthly_price=9.99,
        fare_discount_pct=10.0,
        surge_cap_multiplier=2.0,
        priority_matching=False,
        description=(
            "10% off every ride + surge price capped at 2.0×. "
            "Billed monthly. Cancel any time."
        ),
    ),
    MembershipPlan.premium: PlanDetails(
        plan=MembershipPlan.premium,
        monthly_price=19.99,
        fare_discount_pct=20.0,
        surge_cap_multiplier=1.5,
        priority_matching=True,
        description=(
            "20% off every ride + surge price capped at 1.5× + priority matching. "
            "Billed monthly. Cancel any time."
        ),
    ),
}

MEMBERSHIP_DURATION_DAYS: int = 30


def get_all_plans() -> list[PlanDetails]:
    """Return all available membership plans."""
    return list(_PLAN_CATALOGUE.values())


def plan_benefits(plan: MembershipPlan) -> PlanDetails:
    """Return the PlanDetails for a given plan."""
    return _PLAN_CATALOGUE[plan]


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, easy to unit test
# ---------------------------------------------------------------------------


@dataclass
class MembershipBenefits:
    """Benefits applicable to a single fare calculation."""

    fare_discount_pct: float
    surge_cap_multiplier: float
    priority_matching: bool
    plan: MembershipPlan


def benefits_active(membership: RiderMembership, now: datetime | None = None) -> bool:
    """Return True when the membership is currently granting benefits.

    Benefits are active when status is active OR cancelled-but-not-yet-expired.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if membership.status == MembershipStatus.expired:
        return False

    expires_at = membership.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return now < expires_at


def apply_membership_discount(fare: float, fare_discount_pct: float) -> float:
    """Apply the membership fare discount and return the discounted fare.

    Args:
        fare: Original fare in dollars.
        fare_discount_pct: Discount percentage (e.g. 10.0 means 10%).

    Returns:
        Discounted fare, never negative.
    """
    discount = fare * (fare_discount_pct / 100.0)
    return max(0.0, round(fare - discount, 2))


def apply_surge_cap(multiplier: float, surge_cap_multiplier: float) -> float:
    """Cap the demand multiplier at the member's surge ceiling.

    Args:
        multiplier: The current demand multiplier.
        surge_cap_multiplier: The maximum multiplier allowed for this plan.

    Returns:
        min(multiplier, surge_cap_multiplier).
    """
    return min(multiplier, surge_cap_multiplier)


def get_active_benefits(
    membership: RiderMembership | None,
    now: datetime | None = None,
) -> MembershipBenefits | None:
    """Return active benefits for a membership, or None if no benefits apply."""
    if membership is None:
        return None
    if not benefits_active(membership, now):
        return None
    return MembershipBenefits(
        fare_discount_pct=membership.fare_discount_pct,
        surge_cap_multiplier=membership.surge_cap_multiplier,
        priority_matching=membership.priority_matching,
        plan=membership.plan,
    )


# ---------------------------------------------------------------------------
# Async DB operations
# ---------------------------------------------------------------------------


async def get_active_membership(
    db: AsyncSession, rider_id: int
) -> RiderMembership | None:
    """Return the rider's current membership that is granting benefits, or None.

    A membership grants benefits when status is active OR cancelled with an
    expires_at in the future.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(RiderMembership).where(
            RiderMembership.rider_id == rider_id,
            RiderMembership.status != MembershipStatus.expired,
            RiderMembership.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def subscribe(
    db: AsyncSession,
    rider_id: int,
    plan: MembershipPlan,
    now: datetime | None = None,
) -> RiderMembership:
    """Subscribe the rider to a membership plan.

    If the rider already has an active membership on the same plan, it is
    returned unchanged.  If they are on a different plan, the existing
    membership is cancelled immediately (no pro-rated refund logic — that
    belongs in a billing service) and a new one is created.

    Args:
        db: Database session.
        rider_id: ID of the rider subscribing.
        plan: The plan to subscribe to.
        now: Override for "now" (useful in tests).

    Returns:
        The active RiderMembership row.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    existing = await get_active_membership(db, rider_id)
    if existing is not None:
        if existing.plan == plan and existing.status == MembershipStatus.active:
            # Already subscribed to this plan — idempotent return.
            return existing
        # Cancel the existing plan immediately before switching.
        existing.status = MembershipStatus.cancelled
        existing.cancelled_at = now
        db.add(existing)

    details = plan_benefits(plan)
    membership = RiderMembership(
        rider_id=rider_id,
        plan=plan,
        status=MembershipStatus.active,
        started_at=now,
        expires_at=now + timedelta(days=MEMBERSHIP_DURATION_DAYS),
        monthly_price=details.monthly_price,
        fare_discount_pct=details.fare_discount_pct,
        surge_cap_multiplier=details.surge_cap_multiplier,
        priority_matching=details.priority_matching,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def cancel_membership(
    db: AsyncSession, rider_id: int
) -> RiderMembership | None:
    """Cancel the rider's active membership.

    Benefits remain valid until expires_at (end of current billing period).
    Returns the updated membership, or None if no active membership exists.
    """
    membership = await get_active_membership(db, rider_id)
    if membership is None:
        return None

    if membership.status == MembershipStatus.cancelled:
        # Already cancelled — return as-is (idempotent).
        return membership

    membership.status = MembershipStatus.cancelled
    membership.cancelled_at = datetime.now(timezone.utc)
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def get_admin_summary(db: AsyncSession) -> dict:
    """Return aggregate membership statistics for the admin endpoint."""
    now = datetime.now(timezone.utc)

    # Active memberships (status=active AND not expired)
    active_result = await db.execute(
        select(
            RiderMembership.plan,
            func.count(RiderMembership.id).label("count"),
        ).where(
            RiderMembership.status == MembershipStatus.active,
            RiderMembership.expires_at > now,
        ).group_by(RiderMembership.plan)
    )
    plan_counts: dict[str, int] = {row.plan.value: row.count for row in active_result}

    basic_active = plan_counts.get("basic", 0)
    premium_active = plan_counts.get("premium", 0)
    total_active = basic_active + premium_active

    # Cancellations this calendar month
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cancelled_result = await db.execute(
        select(func.count(RiderMembership.id)).where(
            RiderMembership.cancelled_at >= month_start,
        )
    )
    total_cancelled = cancelled_result.scalar_one() or 0

    # Revenue estimate: sum of monthly_price for all active memberships
    revenue_result = await db.execute(
        select(func.sum(RiderMembership.monthly_price)).where(
            RiderMembership.status == MembershipStatus.active,
            RiderMembership.expires_at > now,
        )
    )
    revenue_estimate = float(revenue_result.scalar_one() or 0.0)

    return {
        "total_active": total_active,
        "basic_active": basic_active,
        "premium_active": premium_active,
        "total_cancelled_this_month": total_cancelled,
        "monthly_revenue_estimate": round(revenue_estimate, 2),
    }
