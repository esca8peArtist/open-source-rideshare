"""Driver earnings summary endpoint.

GET /driver/me/earnings-summary
  Returns a snapshot of the authenticated driver's earnings across four time
  windows — today, this week (ISO), this month, and lifetime — plus the
  pending payout amount and projected next payout date.

  This endpoint is a cooperative transparency differentiator: drivers can
  see exactly how their pay breaks down without navigating complex reports.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.user import User
from app.schemas.driver_earnings_summary import DriverEarningsSummary
from app.services.driver_earnings_summary import get_driver_earnings_summary
from app.services.pricing import get_pricing_params

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/earnings-summary", response_model=DriverEarningsSummary)
async def get_earnings_summary(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverEarningsSummary:
    """Return an earnings snapshot for the authenticated driver.

    Provides today, this-week, this-month, and lifetime totals broken down
    into gross earnings, platform fee, net earnings, and tips.  Also includes
    pending_payout_usd (rides not yet covered by a completed DriverPayout)
    and next_payout_date (derived from the driver's bank account frequency,
    or null if no bank account is linked).
    """
    params = get_pricing_params()
    return await get_driver_earnings_summary(db, driver.id, params["platform_fee_percent"])
