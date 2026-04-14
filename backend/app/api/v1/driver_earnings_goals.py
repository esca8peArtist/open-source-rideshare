"""Driver earnings goals API endpoints.

Driver-facing:
  GET    /drivers/me/earnings-goal          — get current goal + live progress
  PUT    /drivers/me/earnings-goal          — set or update the goal
  DELETE /drivers/me/earnings-goal          — remove the goal

All endpoints require driver authentication.  Progress is computed live
from completed rides in the current period (no persisted aggregates).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.driver_earnings_goal import (
    EarningsGoalProgressResponse,
    EarningsGoalRequest,
    EarningsGoalResponse,
)
from app.services.driver_earnings_goals import (
    delete_goal,
    get_goal_progress,
    set_goal,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-earnings-goals"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_driver_profile_id(db: AsyncSession, user: User) -> int:
    """Resolve the DriverProfile.id for the authenticated user or raise 404."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )
    return profile.id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/earnings-goal",
    response_model=EarningsGoalProgressResponse,
    summary="Get earnings goal with live progress",
)
async def get_my_earnings_goal(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver's earnings goal and real-time progress for the current period.

    Progress is computed live from completed rides — no cached state.
    Returns 404 if the driver has not set a goal yet.
    """
    profile_id = await _get_driver_profile_id(db, user)
    progress = await get_goal_progress(db, profile_id)
    if progress is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No earnings goal set. Use PUT /drivers/me/earnings-goal to create one.",
        )
    return progress


@router.put(
    "/drivers/me/earnings-goal",
    response_model=EarningsGoalResponse,
    summary="Set or update earnings goal",
)
async def upsert_earnings_goal(
    req: EarningsGoalRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the driver's earnings goal.

    Replaces the previous goal in-place (upsert semantics).  The target
    amount must be between $1 and $2,000.
    """
    profile_id = await _get_driver_profile_id(db, user)
    goal = await set_goal(db, profile_id, req.period_type, req.target_amount)
    await db.commit()
    await db.refresh(goal)
    return EarningsGoalResponse.model_validate(goal)


@router.delete(
    "/drivers/me/earnings-goal",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove earnings goal",
)
async def delete_earnings_goal(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Delete the driver's earnings goal.

    Returns 204 on success.  Returns 404 if no goal exists.
    """
    profile_id = await _get_driver_profile_id(db, user)
    deleted = await delete_goal(db, profile_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No earnings goal to delete.",
        )
    await db.commit()
