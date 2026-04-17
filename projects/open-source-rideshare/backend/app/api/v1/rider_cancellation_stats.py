"""Rider cancellation statistics endpoints.

GET  /riders/me/cancel-stats            — rider views their own stats
GET  /admin/riders/{rider_id}/cancel-stats  — admin views any rider's stats
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.ride import CancellationCategory
from app.models.user import User
from app.services.rider_cancellation_stats import get_rider_cancel_stats

router = APIRouter(tags=["rider-cancel-stats"])


class RiderCancelStatsResponse(BaseModel):
    rider_id: int
    total_rides_requested: int
    total_cancellations: int
    cancellations_in_grace_period: int
    cancellations_with_fee: int
    cancellation_rate: float
    last_cancel_at: datetime | None
    last_cancel_category: CancellationCategory | None
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("/riders/me/cancel-stats", response_model=RiderCancelStatsResponse)
async def get_my_cancel_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated rider's lifetime cancellation statistics."""
    stats = await get_rider_cancel_stats(db, rider_id=user.id)
    if stats is None:
        # No rides requested yet — return zeroed defaults rather than 404
        return RiderCancelStatsResponse(
            rider_id=user.id,
            total_rides_requested=0,
            total_cancellations=0,
            cancellations_in_grace_period=0,
            cancellations_with_fee=0,
            cancellation_rate=0.0,
            last_cancel_at=None,
            last_cancel_category=None,
            updated_at=datetime.utcnow(),
        )
    return stats


@router.get("/admin/riders/{rider_id}/cancel-stats", response_model=RiderCancelStatsResponse)
async def admin_get_rider_cancel_stats(
    rider_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return cancellation statistics for any rider."""
    stats = await get_rider_cancel_stats(db, rider_id=rider_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="No cancellation stats found for this rider")
    return stats
