"""Surge price lock API endpoints.

Rider-facing:
  POST   /riders/me/surge-lock   — create (or replace) a surge price lock
  GET    /riders/me/surge-lock   — get current active lock
  DELETE /riders/me/surge-lock   — cancel active lock
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.surge_price_lock import (
    SurgePriceLockCancelResponse,
    SurgePriceLockRequest,
    SurgePriceLockResponse,
)
from app.services.surge_price_lock import (
    LOCK_DURATION_MINUTES,
    build_response,
    cancel_lock,
    create_lock,
    get_active_lock,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["surge-price-lock"])


# ---------------------------------------------------------------------------
# Helper: resolve the demand multiplier for a given location
# ---------------------------------------------------------------------------


async def _get_multiplier_for_location(lat: float, lon: float) -> float:
    """Return the current demand multiplier for a pickup location.

    Falls back to 1.0 if Redis (demand service) is unavailable.
    """
    try:
        from app.services.demand_pricing import get_demand_info
        from app.core.redis import get_redis

        redis_client = await get_redis()
        demand = await get_demand_info(redis_client, lat, lon)
        return demand.multiplier
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/surge-lock",
    response_model=SurgePriceLockResponse,
    status_code=status.HTTP_201_CREATED,
    summary=f"Lock the current surge multiplier for {LOCK_DURATION_MINUTES} minutes",
)
async def create_surge_lock(
    req: SurgePriceLockRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Capture the current demand multiplier for the rider's pickup location.

    The locked multiplier will be applied when the rider creates a ride within
    the lock window, protecting them from surge price increases while they
    complete their booking.

    If an existing active lock is present it is automatically cancelled and
    replaced with the new one.

    **Lock window**: {LOCK_DURATION_MINUTES} minutes from creation.

    **Effect at booking**: if a ride is requested while this lock is active,
    the `locked_multiplier` is used in place of the current demand multiplier
    when calculating the fare estimate.
    """
    multiplier = await _get_multiplier_for_location(req.pickup_lat, req.pickup_lon)
    lock = await create_lock(
        db,
        rider_id=user.id,
        pickup_lat=req.pickup_lat,
        pickup_lon=req.pickup_lon,
        pickup_address=req.pickup_address,
        multiplier=multiplier,
    )
    return build_response(lock)


@router.get(
    "/riders/me/surge-lock",
    response_model=SurgePriceLockResponse,
    summary="Get the rider's current active surge price lock",
)
async def get_surge_lock(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current active surge price lock for the authenticated rider.

    Returns **404** if there is no active lock (lock was used, cancelled, or
    has expired).
    """
    lock = await get_active_lock(db, user.id)
    if lock is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active surge price lock found.",
        )
    return build_response(lock)


@router.delete(
    "/riders/me/surge-lock",
    response_model=SurgePriceLockCancelResponse,
    summary="Cancel the rider's active surge price lock",
)
async def delete_surge_lock(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel the current active surge price lock.

    Returns **404** if there is no active lock to cancel.
    """
    cancelled = await cancel_lock(db, user.id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active surge price lock to cancel.",
        )
    return SurgePriceLockCancelResponse(
        cancelled=True,
        message="Surge price lock cancelled successfully.",
    )
