"""Rider spending summary endpoint.

GET /riders/me/spending-summary
  Returns a snapshot of the authenticated rider's spending across four time
  windows — today, this week (ISO), this month, and lifetime — plus the
  total tips the rider has given, total promo savings accumulated, and
  their most frequently travelled route.

  This endpoint mirrors the driver earnings summary and gives riders
  transparent access to their own spending data.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_rider
from app.models.user import User
from app.schemas.rider_spending_summary import RiderSpendingSummary
from app.services.rider_spending_summary import get_rider_spending_summary

router = APIRouter(prefix="/riders", tags=["riders"])


@router.get("/me/spending-summary", response_model=RiderSpendingSummary)
async def get_spending_summary(
    rider: User = Depends(require_rider),
    db: AsyncSession = Depends(get_db),
) -> RiderSpendingSummary:
    """Return a spending snapshot for the authenticated rider.

    Provides today, this-week, this-month, and lifetime totals broken down
    into trip count, total spent, and average fare.  Also includes
    total_tips_given, total_promo_savings, and the most_frequent_route
    (pickup → dropoff pair with the highest repeat count, or null if no
    completed rides exist).

    Only completed rides with a non-null actual_fare are counted.
    All period boundaries use UTC: today starts at midnight, this_week
    starts on Monday 00:00, and this_month starts on the 1st at 00:00.
    """
    return await get_rider_spending_summary(db, rider.id)
