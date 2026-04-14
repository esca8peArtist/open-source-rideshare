"""Service layer for the driver subscription plan feature."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_subscription import (
    PLAN_DETAILS,
    STANDARD_COMMISSION_PCT,
    DriverSubscription,
    DriverSubscriptionPlan,
    DriverSubscriptionStatus,
)

DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _expires_at(plan: DriverSubscriptionPlan, from_dt: datetime | None = None) -> datetime:
    """Calculate the expiry datetime for a new subscription of the given plan."""
    base = from_dt or _now()
    days = PLAN_DETAILS[plan]["billing_days"]
    return base + timedelta(days=days)


def _price(plan: DriverSubscriptionPlan) -> float:
    return PLAN_DETAILS[plan]["price"]


# ---------------------------------------------------------------------------
# Active subscription query helpers
# ---------------------------------------------------------------------------


async def get_active_subscription(
    db: AsyncSession, driver_id: int
) -> DriverSubscription | None:
    """Return the driver's current active subscription, or None."""
    now = _now()
    result = await db.execute(
        select(DriverSubscription)
        .where(
            DriverSubscription.driver_id == driver_id,
            DriverSubscription.status == DriverSubscriptionStatus.active,
            DriverSubscription.expires_at > now,
        )
        .order_by(DriverSubscription.expires_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_subscription_by_id(
    db: AsyncSession, subscription_id: int
) -> DriverSubscription | None:
    result = await db.execute(
        select(DriverSubscription).where(DriverSubscription.id == subscription_id)
    )
    return result.scalar_one_or_none()


async def get_driver_commission_pct(db: AsyncSession, driver_id: int) -> float:
    """Return the commission percentage for a driver (0.0 if subscribed, 15.0 otherwise)."""
    sub = await get_active_subscription(db, driver_id)
    if sub is not None:
        return sub.commission_pct
    return STANDARD_COMMISSION_PCT


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------


async def subscribe(
    db: AsyncSession,
    driver_id: int,
    plan: DriverSubscriptionPlan,
    *,
    auto_renew: bool = True,
    stripe_subscription_id: str | None = None,
) -> DriverSubscription:
    """Subscribe a driver to a plan.

    Raises ValueError if the driver already has an active subscription.
    """
    existing = await get_active_subscription(db, driver_id)
    if existing is not None:
        raise ValueError(
            f"Driver {driver_id} already has an active {existing.plan.value} subscription "
            f"(expires {existing.expires_at.isoformat()}).  Cancel it before subscribing again."
        )

    now = _now()
    sub = DriverSubscription(
        driver_id=driver_id,
        plan=plan,
        status=DriverSubscriptionStatus.active,
        started_at=now,
        expires_at=_expires_at(plan, from_dt=now),
        price=_price(plan),
        commission_pct=0.0,
        auto_renew=auto_renew,
        stripe_subscription_id=stripe_subscription_id,
    )
    db.add(sub)
    await db.flush()
    await db.refresh(sub)
    return sub


async def cancel_subscription(
    db: AsyncSession, driver_id: int
) -> DriverSubscription:
    """Cancel the driver's active subscription.

    Benefits remain valid until expires_at.  Raises ValueError if no active
    subscription exists.
    """
    sub = await get_active_subscription(db, driver_id)
    if sub is None:
        raise ValueError(f"Driver {driver_id} has no active subscription to cancel.")

    sub.status = DriverSubscriptionStatus.cancelled
    sub.auto_renew = False
    sub.cancelled_at = _now()
    await db.flush()
    await db.refresh(sub)
    return sub


async def update_auto_renew(
    db: AsyncSession, driver_id: int, auto_renew: bool
) -> DriverSubscription:
    """Update the auto-renew flag on an active subscription.

    Raises ValueError if no active subscription exists.
    """
    sub = await get_active_subscription(db, driver_id)
    if sub is None:
        raise ValueError(f"Driver {driver_id} has no active subscription to update.")

    sub.auto_renew = auto_renew
    await db.flush()
    await db.refresh(sub)
    return sub


async def expire_subscriptions(db: AsyncSession) -> int:
    """Mark all past-due active subscriptions as expired.

    Returns the count of subscriptions transitioned.  Intended to be called
    from a background scheduler.
    """
    now = _now()
    result = await db.execute(
        select(DriverSubscription).where(
            DriverSubscription.status == DriverSubscriptionStatus.active,
            DriverSubscription.expires_at <= now,
        )
    )
    subs: Sequence[DriverSubscription] = result.scalars().all()
    for sub in subs:
        sub.status = DriverSubscriptionStatus.expired
    await db.flush()
    return len(subs)


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------


async def list_driver_subscriptions(
    db: AsyncSession,
    driver_id: int,
    *,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[DriverSubscription]:
    """Return all subscriptions (any status) for a driver, newest first."""
    limit = min(limit, MAX_PAGE_SIZE)
    result = await db.execute(
        select(DriverSubscription)
        .where(DriverSubscription.driver_id == driver_id)
        .order_by(DriverSubscription.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_all_subscriptions(
    db: AsyncSession,
    *,
    status: DriverSubscriptionStatus | None = None,
    plan: DriverSubscriptionPlan | None = None,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[DriverSubscription]:
    """Admin: list all subscriptions, optionally filtered by status and/or plan."""
    limit = min(limit, MAX_PAGE_SIZE)
    query = select(DriverSubscription).order_by(DriverSubscription.started_at.desc())
    if status is not None:
        query = query.where(DriverSubscription.status == status)
    if plan is not None:
        query = query.where(DriverSubscription.plan == plan)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_subscription_stats(db: AsyncSession) -> dict:
    """Admin: aggregate counts and revenue by status/plan."""
    now = _now()

    # Count active (not expired)
    res_active_weekly = await db.execute(
        select(func.count()).where(
            DriverSubscription.status == DriverSubscriptionStatus.active,
            DriverSubscription.plan == DriverSubscriptionPlan.weekly,
            DriverSubscription.expires_at > now,
        )
    )
    res_active_monthly = await db.execute(
        select(func.count()).where(
            DriverSubscription.status == DriverSubscriptionStatus.active,
            DriverSubscription.plan == DriverSubscriptionPlan.monthly,
            DriverSubscription.expires_at > now,
        )
    )
    res_cancelled = await db.execute(
        select(func.count()).where(
            DriverSubscription.status == DriverSubscriptionStatus.cancelled,
        )
    )
    res_expired = await db.execute(
        select(func.count()).where(
            DriverSubscription.status == DriverSubscriptionStatus.expired,
        )
    )

    weekly_active = res_active_weekly.scalar_one()
    monthly_active = res_active_monthly.scalar_one()
    total_active = weekly_active + monthly_active
    total_cancelled = res_cancelled.scalar_one()
    total_expired = res_expired.scalar_one()

    weekly_price = PLAN_DETAILS[DriverSubscriptionPlan.weekly]["price"]
    monthly_price = PLAN_DETAILS[DriverSubscriptionPlan.monthly]["price"]
    active_revenue_weekly = weekly_active * weekly_price
    active_revenue_monthly = monthly_active * monthly_price

    return {
        "total_active": total_active,
        "total_cancelled": total_cancelled,
        "total_expired": total_expired,
        "weekly_active": weekly_active,
        "monthly_active": monthly_active,
        "active_revenue_weekly": active_revenue_weekly,
        "active_revenue_monthly": active_revenue_monthly,
        "active_revenue_total": active_revenue_weekly + active_revenue_monthly,
    }
