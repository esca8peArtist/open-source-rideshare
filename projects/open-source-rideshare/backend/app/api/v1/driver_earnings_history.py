"""Driver earnings history endpoint.

GET /driver/me/earnings-history
  Returns a week-by-week breakdown of the authenticated driver's completed-ride
  earnings, tips, and ride counts over a configurable trailing window.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_earnings_history import DriverEarningsHistory
from app.services.driver_earnings_history import (
    HISTORY_WEEKS_DEFAULT,
    HISTORY_WEEKS_MAX,
    get_driver_earnings_history,
)

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/earnings-history", response_model=DriverEarningsHistory)
async def get_earnings_history(
    weeks: int = Query(
        default=HISTORY_WEEKS_DEFAULT,
        ge=1,
        le=HISTORY_WEEKS_MAX,
        description="Number of trailing weeks to include (1–52).",
    ),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverEarningsHistory:
    """Return a week-by-week earnings breakdown for the authenticated driver."""
    return await get_driver_earnings_history(db=db, driver_id=driver.id, weeks=weeks)
