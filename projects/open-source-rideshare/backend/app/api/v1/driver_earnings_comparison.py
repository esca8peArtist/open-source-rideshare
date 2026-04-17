"""Driver earnings comparison API endpoint.

Shows drivers how their actual OpenRide payouts compare to estimated payouts
on Uber and Lyft for the same trips, using published platform rate cards.

Endpoint:
  GET /drivers/me/earnings-comparison

Query parameters:
  start_date  (date, optional) — inclusive start; defaults to first day of current month
  end_date    (date, optional) — inclusive end; defaults to today

Distinct from:
  - /drivers/me/earnings-summary  — P&L view with expenses offset, no competitor comparison
  - /analytics/driver/tax-summary — annual-only tax view
  - /drivers/me/revenue-projections — forward-looking estimates
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_earnings_comparison import EarningsComparisonResponse
from app.services.driver_earnings_comparison import get_earnings_comparison

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-earnings"])


@router.get(
    "/drivers/me/earnings-comparison",
    response_model=EarningsComparisonResponse,
    summary="Compare OpenRide earnings to estimated Uber/Lyft payouts",
)
async def get_driver_earnings_comparison(
    start_date: date | None = Query(
        None,
        description=(
            "Inclusive start date (YYYY-MM-DD). "
            "Defaults to the first day of the current calendar month."
        ),
    ),
    end_date: date | None = Query(
        None,
        description=(
            "Inclusive end date (YYYY-MM-DD). "
            "Defaults to today."
        ),
    ),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> EarningsComparisonResponse:
    """Compare your actual OpenRide earnings to estimated Uber and Lyft payouts.

    For every completed ride in the requested period that has distance and
    duration data, the service computes:

    - **Actual OpenRide payout** — from Payment records (or fare fields as fallback)
      plus any tips you received.
    - **Estimated Uber payout** — using the 2025 US national average UberX rate card
      (base + per-min + per-mile, less the ~25% platform fee).
    - **Estimated Lyft payout** — using the 2025 US national average Lyft Standard
      rate card.

    The response includes total payouts, per-ride/per-mile/per-hour averages,
    and the absolute and percentage advantage of OpenRide over each competitor.

    Rides missing distance or duration data are excluded from the comparison
    and counted in `rides_excluded`.

    Competitor estimates use national averages; actual rates vary by city,
    time of day, and surge conditions. See `methodology_note` in the response.
    """
    return await get_earnings_comparison(
        db=db,
        driver_id=driver.id,
        start_date=start_date,
        end_date=end_date,
    )
