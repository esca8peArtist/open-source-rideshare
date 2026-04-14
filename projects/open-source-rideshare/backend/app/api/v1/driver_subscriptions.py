"""Driver subscription plan API endpoints.

Drivers can opt into a flat-fee weekly or monthly subscription plan instead
of paying per-ride commission (default 15 %).  While a subscription is active
the commission rate is 0 %.

Driver-facing:
  GET    /drivers/me/subscription           — active subscription (or 404 if none)
  GET    /drivers/me/subscriptions          — full history (all statuses, paginated)
  POST   /drivers/me/subscription           — subscribe to a plan
  PATCH  /drivers/me/subscription           — update auto_renew flag
  DELETE /drivers/me/subscription           — cancel active subscription

Plan info (public):
  GET    /driver-subscriptions/plans        — list available plan details

Admin-facing:
  GET    /admin/driver-subscriptions        — all subscriptions (paginated, filterable)
  GET    /admin/driver-subscriptions/stats  — aggregate counts and revenue
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_driver
from app.models.driver_subscription import DriverSubscriptionPlan, DriverSubscriptionStatus
from app.models.user import User
from app.schemas.driver_subscription import (
    AdminDriverSubscriptionResponse,
    DriverSubscriptionResponse,
    PlanDetails,
    SubscribeRequest,
    SubscriptionStatsResponse,
    UpdateSubscriptionRequest,
    get_all_plan_details,
)
from app.services.driver_subscriptions import (
    cancel_subscription,
    get_active_subscription,
    get_subscription_stats,
    list_all_subscriptions,
    list_driver_subscriptions,
    subscribe,
    update_auto_renew,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-subscriptions"])


# ---------------------------------------------------------------------------
# Public — plan catalogue
# ---------------------------------------------------------------------------


@router.get(
    "/driver-subscriptions/plans",
    response_model=list[PlanDetails],
    summary="List available driver subscription plans",
)
async def list_plans() -> list[PlanDetails]:
    """Return static details for all subscription plans."""
    return get_all_plan_details()


# ---------------------------------------------------------------------------
# Driver — own subscription
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/subscription",
    response_model=DriverSubscriptionResponse,
    summary="Get current active subscription",
)
async def get_my_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_driver),
) -> DriverSubscriptionResponse:
    sub = await get_active_subscription(db, current_user.id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )
    return DriverSubscriptionResponse.model_validate(sub)


@router.get(
    "/drivers/me/subscriptions",
    response_model=list[DriverSubscriptionResponse],
    summary="List all subscriptions (history)",
)
async def list_my_subscriptions(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_driver),
) -> list[DriverSubscriptionResponse]:
    subs = await list_driver_subscriptions(db, current_user.id, offset=offset, limit=limit)
    return [DriverSubscriptionResponse.model_validate(s) for s in subs]


@router.post(
    "/drivers/me/subscription",
    response_model=DriverSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a plan",
)
async def create_subscription(
    body: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_driver),
) -> DriverSubscriptionResponse:
    try:
        sub = await subscribe(
            db,
            current_user.id,
            body.plan,
            auto_renew=body.auto_renew,
            stripe_subscription_id=body.stripe_subscription_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return DriverSubscriptionResponse.model_validate(sub)


@router.patch(
    "/drivers/me/subscription",
    response_model=DriverSubscriptionResponse,
    summary="Update auto-renew on active subscription",
)
async def patch_subscription(
    body: UpdateSubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_driver),
) -> DriverSubscriptionResponse:
    try:
        sub = await update_auto_renew(db, current_user.id, body.auto_renew)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DriverSubscriptionResponse.model_validate(sub)


@router.delete(
    "/drivers/me/subscription",
    response_model=DriverSubscriptionResponse,
    summary="Cancel active subscription",
)
async def cancel_my_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_driver),
) -> DriverSubscriptionResponse:
    try:
        sub = await cancel_subscription(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DriverSubscriptionResponse.model_validate(sub)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@router.get(
    "/admin/driver-subscriptions/stats",
    response_model=SubscriptionStatsResponse,
    summary="Aggregate driver subscription stats",
)
async def admin_subscription_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SubscriptionStatsResponse:
    stats = await get_subscription_stats(db)
    return SubscriptionStatsResponse(**stats)


@router.get(
    "/admin/driver-subscriptions",
    response_model=list[AdminDriverSubscriptionResponse],
    summary="List all driver subscriptions",
)
async def admin_list_subscriptions(
    status_filter: DriverSubscriptionStatus | None = Query(None, alias="status"),
    plan_filter: DriverSubscriptionPlan | None = Query(None, alias="plan"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[AdminDriverSubscriptionResponse]:
    subs = await list_all_subscriptions(
        db,
        status=status_filter,
        plan=plan_filter,
        offset=offset,
        limit=limit,
    )
    return [AdminDriverSubscriptionResponse.model_validate(s) for s in subs]
