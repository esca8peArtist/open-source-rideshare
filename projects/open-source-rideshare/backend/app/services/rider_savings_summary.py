"""Rider savings summary service.

Computes a rider's cumulative fare savings compared to Uber and Lyft by
re-estimating what each completed ride would have cost on those platforms,
then comparing to what the rider actually paid on OpenRide.

Public API:
    get_rider_savings_summary(db, rider_id, start_date, end_date)
        → RiderSavingsSummary

Methodology:
    For each completed ride with distance_km and duration_min populated, we
    estimate the Uber and Lyft fare using 2025 US national average rate cards
    (the same cards used by GET /pricing/fare-preview).  The difference
    between the estimated competitor fare and the actual OpenRide fare is the
    per-ride saving.

    Rides without distance or duration data are included in
    total_openride_spend_usd but excluded from the savings comparison — the
    rides_included_in_comparison field tells the caller how many rides
    contributed to the estimate.

    Tips are reported separately; they go 100% to the driver on all platforms
    and are not included in the competitor fare comparison.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.rider_savings_summary import RiderSavingsSummary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 2025 competitor rate cards (US national averages)
# Source: RideGuru national average rate survey; rideshare driver community
# aggregates.  Rates vary significantly by city, time, and surge conditions.
# ---------------------------------------------------------------------------

_KM_TO_MILES: float = 0.621371

# Uber UberX
_UBER_BASE_FARE: float = 1.38       # USD
_UBER_PER_MIN: float = 0.20         # USD / minute
_UBER_PER_MILE: float = 0.84        # USD / mile
_UBER_PLATFORM_NAME: str = "Uber (UberX)"

# Lyft Standard
_LYFT_BASE_FARE: float = 1.25       # USD
_LYFT_PER_MIN: float = 0.22         # USD / minute
_LYFT_PER_MILE: float = 0.83        # USD / mile
_LYFT_PLATFORM_NAME: str = "Lyft (Standard)"

_METHODOLOGY_NOTE: str = (
    "Competitor fares are estimates based on 2025 US national average rate cards for "
    "UberX (base $1.38 + $0.20/min + $0.84/mile) and Lyft Standard (base $1.25 + "
    "$0.22/min + $0.83/mile), applied to each ride's recorded distance and duration.  "
    "Actual competitor fares vary significantly by city, time of day, surge conditions, "
    "and driver incentive programmes.  This comparison is for informational purposes "
    "only.  Rides without distance/duration data are excluded from the comparison."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _estimate_competitor_fare(
    distance_km: float,
    duration_min: float,
    base_fare: float,
    per_min: float,
    per_mile: float,
) -> float:
    """Estimate a competitor fare from distance and duration.

    Uses the competitor's published rate structure:
        fare = base_fare + per_min * duration_min + per_mile * (distance_km * KM_TO_MILES)

    Returns the fare rounded to 2 decimal places.  Enforces a $3.00 minimum
    fare (standard floor across US rideshare markets in 2025).
    """
    miles = distance_km * _KM_TO_MILES
    fare = base_fare + per_min * duration_min + per_mile * miles
    return round(max(fare, 3.00), 2)


def _build_transparency_note(
    rides_count: int,
    total_saved_vs_uber: float,
    total_saved_vs_lyft: float,
) -> str:
    """Build a human-readable savings summary sentence for the rider app UI."""
    if rides_count == 0:
        return (
            "No completed rides found for the selected period.  Take your first "
            "OpenRide to start tracking your savings vs. Uber and Lyft."
        )

    # Format helpers
    def _fmt(v: float) -> str:
        return f"${abs(v):,.2f}"

    uber_part = (
        f"saved {_fmt(total_saved_vs_uber)} vs. Uber"
        if total_saved_vs_uber >= 0
        else f"paid {_fmt(total_saved_vs_uber)} more than Uber estimates"
    )
    lyft_part = (
        f"saved {_fmt(total_saved_vs_lyft)} vs. Lyft"
        if total_saved_vs_lyft >= 0
        else f"paid {_fmt(total_saved_vs_lyft)} more than Lyft estimates"
    )
    return (
        f"Across {rides_count} ride{'s' if rides_count != 1 else ''} on OpenRide, "
        f"you {uber_part} and {lyft_part} — money that stayed with you and your driver "
        "instead of going to a corporate platform."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_rider_savings_summary(
    db: AsyncSession,
    rider_id: int,
    start_date: Optional[date],
    end_date: Optional[date],
) -> RiderSavingsSummary:
    """Compute cumulative savings summary for rider_id.

    Args:
        db:          Async database session.
        rider_id:    ID of the authenticated rider.
        start_date:  Optional inclusive start date (filters on requested_at).
        end_date:    Optional inclusive end date (filters on requested_at).

    Returns:
        RiderSavingsSummary with spend totals, savings vs. competitors, and
        metadata notes.
    """
    # Build the query for completed rides belonging to this rider
    conditions = [
        Ride.rider_id == rider_id,
        Ride.status == RideStatus.COMPLETED,
    ]

    if start_date is not None:
        start_dt = datetime(
            start_date.year, start_date.month, start_date.day,
            tzinfo=timezone.utc,
        )
        conditions.append(Ride.requested_at >= start_dt)

    if end_date is not None:
        # end_date is inclusive: include the full day
        end_dt = datetime(
            end_date.year, end_date.month, end_date.day,
            23, 59, 59, 999999,
            tzinfo=timezone.utc,
        )
        conditions.append(Ride.requested_at <= end_dt)

    stmt = select(Ride).where(and_(*conditions))
    result = await db.execute(stmt)
    rides = result.scalars().all()

    # Accumulators
    total_openride_spend = 0.0
    total_tips = 0.0
    total_uber_est = 0.0
    total_lyft_est = 0.0
    rides_in_comparison = 0

    for ride in rides:
        fare = ride.actual_fare or 0.0
        tip = ride.tip_amount or 0.0
        total_openride_spend += fare
        total_tips += tip

        if ride.distance_km and ride.duration_min:
            uber_fare = _estimate_competitor_fare(
                distance_km=ride.distance_km,
                duration_min=ride.duration_min,
                base_fare=_UBER_BASE_FARE,
                per_min=_UBER_PER_MIN,
                per_mile=_UBER_PER_MILE,
            )
            lyft_fare = _estimate_competitor_fare(
                distance_km=ride.distance_km,
                duration_min=ride.duration_min,
                base_fare=_LYFT_BASE_FARE,
                per_min=_LYFT_PER_MIN,
                per_mile=_LYFT_PER_MILE,
            )
            total_uber_est += uber_fare
            total_lyft_est += lyft_fare
            rides_in_comparison += 1

    # Round accumulators
    total_openride_spend = round(total_openride_spend, 2)
    total_tips = round(total_tips, 2)
    total_uber_est = round(total_uber_est, 2)
    total_lyft_est = round(total_lyft_est, 2)

    # Savings = what rider would have paid on competitor - what rider paid on OpenRide
    # (uses spend only for rides that have comparison data; exclude rides without
    # distance/duration from the openride side of the savings calc to be apples-to-apples)
    openride_comparable = 0.0
    for ride in rides:
        if ride.distance_km and ride.duration_min:
            openride_comparable += ride.actual_fare or 0.0
    openride_comparable = round(openride_comparable, 2)

    saved_vs_uber = round(total_uber_est - openride_comparable, 2)
    saved_vs_lyft = round(total_lyft_est - openride_comparable, 2)

    n = rides_in_comparison
    avg_uber = round(saved_vs_uber / n, 2) if n > 0 else 0.0
    avg_lyft = round(saved_vs_lyft / n, 2) if n > 0 else 0.0

    transparency_note = _build_transparency_note(
        rides_count=len(rides),
        total_saved_vs_uber=saved_vs_uber,
        total_saved_vs_lyft=saved_vs_lyft,
    )

    return RiderSavingsSummary(
        total_completed_rides=len(rides),
        rides_included_in_comparison=rides_in_comparison,
        total_openride_spend_usd=total_openride_spend,
        total_tips_usd=total_tips,
        total_estimated_uber_spend_usd=total_uber_est,
        total_estimated_lyft_spend_usd=total_lyft_est,
        total_saved_vs_uber_usd=saved_vs_uber,
        total_saved_vs_lyft_usd=saved_vs_lyft,
        avg_saved_per_ride_vs_uber_usd=avg_uber,
        avg_saved_per_ride_vs_lyft_usd=avg_lyft,
        period_start=start_date,
        period_end=end_date,
        methodology_note=_METHODOLOGY_NOTE,
        transparency_note=transparency_note,
    )
