"""Driver welfare summary endpoint.

GET /driver/me/welfare-summary
  Returns a full welfare snapshot for the authenticated driver: shift hours,
  fatigue risk, earnings metrics, insurance status, cooperative standing, a
  personalised welfare note, and links to support resources.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_welfare_summary import DriverWelfareSummary
from app.services.driver_welfare_summary import get_driver_welfare_summary

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/welfare-summary", response_model=DriverWelfareSummary)
async def get_welfare_summary(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverWelfareSummary:
    """Return the welfare summary for the currently authenticated driver."""
    return await get_driver_welfare_summary(db=db, driver_id=driver.id)
