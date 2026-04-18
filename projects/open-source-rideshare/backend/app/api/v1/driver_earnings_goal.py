"""Driver earnings goal endpoints.

GET  /driver/me/earnings-goal  — retrieve the current goal (404 if none set)
PUT  /driver/me/earnings-goal  — create or replace the goal (upsert)
DELETE /driver/me/earnings-goal — remove the goal
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.driver_earnings_goal import DriverEarningsGoal
from app.models.user import User
from app.schemas.driver_earnings_goal import DriverEarningsGoalResponse, DriverEarningsGoalSet

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/earnings-goal", response_model=DriverEarningsGoalResponse)
async def get_earnings_goal(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverEarningsGoalResponse:
    """Return the driver's current earnings goal."""
    result = await db.execute(
        select(DriverEarningsGoal).where(DriverEarningsGoal.driver_id == driver.id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="No earnings goal set")
    return DriverEarningsGoalResponse.model_validate(goal)


@router.put(
    "/me/earnings-goal",
    response_model=DriverEarningsGoalResponse,
    status_code=status.HTTP_200_OK,
)
async def set_earnings_goal(
    req: DriverEarningsGoalSet,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverEarningsGoalResponse:
    """Create or replace the driver's earnings goal (upsert).

    Only one goal exists per driver at a time. Setting a new goal
    replaces any previous goal.
    """
    result = await db.execute(
        select(DriverEarningsGoal).where(DriverEarningsGoal.driver_id == driver.id)
    )
    goal = result.scalar_one_or_none()

    if goal:
        goal.period_type = req.period_type
        goal.target_amount = req.target_amount
        goal.updated_at = datetime.now(timezone.utc)
    else:
        goal = DriverEarningsGoal(
            driver_id=driver.id,
            period_type=req.period_type,
            target_amount=req.target_amount,
        )
        db.add(goal)

    await db.commit()
    await db.refresh(goal)
    return DriverEarningsGoalResponse.model_validate(goal)


@router.delete("/me/earnings-goal", status_code=status.HTTP_204_NO_CONTENT)
async def delete_earnings_goal(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the driver's earnings goal."""
    result = await db.execute(
        select(DriverEarningsGoal).where(DriverEarningsGoal.driver_id == driver.id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="No earnings goal set")
    await db.delete(goal)
    await db.commit()
