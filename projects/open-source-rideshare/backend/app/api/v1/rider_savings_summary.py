"""Rider savings summary API endpoint.

Shows a rider the cumulative fare savings compared to Uber and Lyft across
their completed ride history.

Endpoint:
  GET /riders/me/savings-summary

Query parameters:
  start_date  (date, optional) — inclusive start (YYYY-MM-DD); no default → all history
  end_date    (date, optional) — inclusive end   (YYYY-MM-DD); no default → all history

Authorization: any authenticated user (riders access their own ride history).

Distinct from:
  GET /pricing/fare-preview            — single pre-booking estimate, no auth required
  GET /rides/{id}/fare-breakdown       — per-ride breakdown for a completed ride
  GET /drivers/me/earnings-comparison  — driver-facing earnings vs. platform averages
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_savings_summary import RiderSavingsSummary
from app.services.rider_savings_summary import get_rider_savings_summary

router = APIRouter(tags=["rider-savings"])


@router.get(
    "/riders/me/savings-summary",
    response_model=RiderSavingsSummary,
    status_code=status.HTTP_200_OK,
    summary="Get rider savings summary vs. Uber and Lyft",
    description=(
        "Returns a cumulative breakdown of how much the authenticated rider has "
        "saved compared to Uber and Lyft across their completed ride history.  "
        "For each completed ride with distance and duration data, the endpoint "
        "estimates what the same trip would have cost on Uber (UberX) and Lyft "
        "(Standard) using 2025 US national average rate cards, then compares "
        "that estimate to the actual OpenRide fare.\n\n"
        "**start_date** and **end_date** are optional and inclusive.  When "
        "omitted, all completed rides in the rider's history are included.\n\n"
        "Rides without distance or duration data are counted in "
        "`total_openride_spend_usd` but excluded from the savings comparison — "
        "`rides_included_in_comparison` tells you how many rides contributed "
        "to the estimate.\n\n"
        "Tips are reported separately in `total_tips_usd`; they go 100%% to "
        "the driver on all platforms and are not included in the competitor "
        "savings calculation.\n\n"
        "See `methodology_note` in the response for full disclosure of the "
        "estimation method and its limitations."
    ),
)
async def get_savings_summary(
    start_date: date | None = Query(
        default=None,
        description=(
            "Inclusive start date (YYYY-MM-DD).  When omitted, all rides in "
            "history are included."
        ),
    ),
    end_date: date | None = Query(
        default=None,
        description=(
            "Inclusive end date (YYYY-MM-DD).  When omitted, all rides up to "
            "today are included."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiderSavingsSummary:
    return await get_rider_savings_summary(
        db=db,
        rider_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )
