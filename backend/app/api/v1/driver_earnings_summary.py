"""Driver Earnings P&L Summary API.

Provides a consolidated profit/loss view for a driver: actual ride earnings
(gross fares minus platform fees plus tips) minus logged business expenses,
yielding the driver's true net profit for the requested date range.

Endpoint:
  GET /drivers/me/earnings-summary

Query parameters:
  start_date  (date, optional) — inclusive start; defaults to first day of current month
  end_date    (date, optional) — inclusive end; defaults to today
  breakdown   (none|weekly|monthly, optional) — granularity of sub-period breakdown; default: none

Distinct from:
  - /analytics/driver/tax-summary       — annual only, no expense offset
  - /drivers/me/revenue-projections     — forward-looking estimates, not actuals
  - /drivers/me/expenses/summary        — expenses only, no income side
  - /drivers/me/earnings-comparison     — vs. platform averages, not P&L
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_earnings_summary import BreakdownInterval, EarningsSummaryResponse
from app.services.driver_earnings_summary import get_driver_earnings_summary

logger = logging.getLogger(__name__)
router = APIRouter(tags=["driver-earnings-summary"])


def _first_day_of_current_month() -> date:
    today = datetime.now(tz=timezone.utc).date()
    return today.replace(day=1)


def _today() -> date:
    return datetime.now(tz=timezone.utc).date()


@router.get(
    "/drivers/me/earnings-summary",
    response_model=EarningsSummaryResponse,
    summary="Get driver earnings P&L summary",
    description=(
        "Returns a profit/loss summary for the authenticated driver for the specified "
        "date range. Combines actual ride earnings (gross fares minus platform fees "
        "plus tips) with logged business expenses to show true net profit.\n\n"
        "**start_date** and **end_date** are inclusive. Both default to the current "
        "calendar month when omitted.\n\n"
        "Set **breakdown** to `weekly` or `monthly` to receive a per-sub-period "
        "breakdown in the `periods` list (ordered oldest-to-newest). The top-level "
        "totals always cover the full requested period regardless of breakdown.\n\n"
        "This endpoint is distinct from:\n"
        "- `/analytics/driver/tax-summary` — annual only, no expense offset\n"
        "- `/drivers/me/revenue-projections` — forward-looking estimates, not actuals\n"
        "- `/drivers/me/expenses/summary` — expenses only, no income side"
    ),
)
async def get_earnings_summary(
    start_date: date | None = Query(
        default=None,
        description="Inclusive start date (YYYY-MM-DD). Defaults to the first day of the current month.",
    ),
    end_date: date | None = Query(
        default=None,
        description="Inclusive end date (YYYY-MM-DD). Defaults to today.",
    ),
    breakdown: BreakdownInterval = Query(
        default=BreakdownInterval.NONE,
        description=(
            "Granularity of the optional sub-period breakdown: "
            "none (default), weekly, or monthly."
        ),
    ),
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> EarningsSummaryResponse:
    """Return the driver's earnings P&L summary for the requested period."""
    if start_date is None:
        start_date = _first_day_of_current_month()
    if end_date is None:
        end_date = _today()

    if start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must not be after end_date.",
        )

    return await get_driver_earnings_summary(
        db,
        driver_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        breakdown=breakdown,
    )
