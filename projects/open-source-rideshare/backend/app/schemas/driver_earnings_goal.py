from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_earnings_goal import GoalPeriodType


class DriverEarningsGoalSet(BaseModel):
    period_type: GoalPeriodType
    target_amount: float = Field(..., gt=0, le=10_000, description="Target earnings in USD")


class DriverEarningsGoalResponse(BaseModel):
    id: int
    driver_id: int
    period_type: GoalPeriodType
    target_amount: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
