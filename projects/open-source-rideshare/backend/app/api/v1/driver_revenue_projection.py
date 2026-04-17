"""Driver revenue projection endpoint.

GET /driver/me/revenue-projection
  Returns a forward-looking revenue projection for the authenticated driver
  based on their completed ride history over the last 8 weeks.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_revenue_projection import DriverRevenueProjection
from app.services.driver_revenue_projection import get_driver_revenue_projection

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/revenue-projection", response_model=DriverRevenueProjection)
async def get_revenue_projection(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverRevenueProjection:
    """Return a revenue projection for the currently authenticated driver."""
    return await get_driver_revenue_projection(db=db, driver_id=driver.id)
