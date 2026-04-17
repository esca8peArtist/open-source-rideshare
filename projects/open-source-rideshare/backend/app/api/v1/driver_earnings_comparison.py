"""Driver earnings comparison endpoint.

GET /driver/me/earnings-comparison
  Returns a comparison of the authenticated driver's trailing average weekly
  earnings against the platform-wide average across all active drivers in the
  same period (last 4 weeks).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_earnings_comparison import DriverEarningsComparison
from app.services.driver_earnings_comparison import get_driver_earnings_comparison

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/earnings-comparison", response_model=DriverEarningsComparison)
async def get_earnings_comparison(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverEarningsComparison:
    """Return an earnings comparison for the currently authenticated driver."""
    return await get_driver_earnings_comparison(db=db, driver_id=driver.id)
