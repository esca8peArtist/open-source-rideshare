"""Service layer for driver earnings comparison.

Compares the authenticated driver's trailing average weekly earnings against
the platform-wide average across all active drivers in the same period.

A single aggregating DB query pulls total fares and ride counts grouped by
driver_id.  All ranking and percentile logic runs in Python for testability.

Terminology
-----------
"Active driver" — any driver who completed ≥1 ride in the comparison window.
"Trailing avg weekly earnings" — total completed-ride fares ÷ COMPARISON_WEEKS.
  (Using the full window length as the divisor, not just weeks with rides, keeps
   part-time and full-time drivers on the same scale.)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.driver_earnings_comparison import (
    DriverEarningsComparison,
    EarningsPercentile,
)

# --------------------------------------------------------------------------- #
# Public constants (imported by tests)
# --------------------------------------------------------------------------- #

COMPARISON_WEEKS: int = 4  # trailing window for earnings comparison
WEEKS_PER_MONTH: float = 52.0 / 12.0  # ≈ 4.33 (consistent with revenue projection)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    """Return current UTC time. Patched by tests for determinism."""
    return datetime.now(tz=timezone.utc)


def _compute_percentile(
    driver_avg: float,
    all_avgs: list[float],
) -> EarningsPercentile:
    """Compute rank and percentile for *driver_avg* within *all_avgs*.

    Rank is 1-based (1 = highest earner).  Ties share the same rank (dense
    ranking is NOT used — the driver gets the rank of the first position they
    would occupy after sorting descending).

    Percentile is the proportion of drivers with strictly *lower* average weekly
    earnings, expressed as a percentage (0–100).  Higher is better.

    Parameters
    ----------
    driver_avg:
        The driver's own trailing average weekly earnings.
    all_avgs:
        Trailing average weekly earnings for *every* active driver in the
        period, including the current driver.
    """
    total = len(all_avgs)
    if total == 0:
        return EarningsPercentile(rank=1, total_drivers=0, percentile=0.0)

    # Rank = count of drivers who earn strictly more, plus 1
    rank = sum(1 for avg in all_avgs if avg > driver_avg) + 1

    # Percentile = proportion of drivers who earn strictly less
    count_below = sum(1 for avg in all_avgs if avg < driver_avg)
    percentile = round(count_below / total * 100.0, 1)

    return EarningsPercentile(rank=rank, total_drivers=total, percentile=percentile)


def _compute_difference_pct(
    driver_avg: float,
    platform_avg: float,
) -> Optional[float]:
    """Return percentage difference of driver_avg relative to platform_avg.

    Returns None when platform_avg is 0 (division undefined).
    """
    if platform_avg == 0.0:
        return None
    return round((driver_avg - platform_avg) / platform_avg * 100.0, 1)


def _build_comparison_note(
    driver_avg: float,
    platform_avg: float,
    difference_usd: float,
    difference_pct: Optional[float],
    rank: int,
    total_drivers: int,
    percentile: float,
    period_weeks: int,
) -> str:
    """Generate a human-readable earnings comparison summary."""
    if total_drivers == 0:
        return (
            "No platform earnings data is available yet. "
            "Complete your first rides to unlock earnings comparisons."
        )

    if driver_avg == 0.0 and platform_avg == 0.0:
        return (
            f"No completed rides recorded in the last {period_weeks} weeks for "
            "either you or the platform. Start driving to see your comparison."
        )

    if driver_avg == 0.0:
        return (
            f"You have no completed rides in the last {period_weeks} weeks. "
            f"The platform average is ${platform_avg:.2f}/week across "
            f"{total_drivers} active driver(s)."
        )

    direction = "above" if difference_usd >= 0 else "below"
    abs_diff = abs(difference_usd)

    pct_fragment = ""
    if difference_pct is not None:
        abs_pct = abs(difference_pct)
        pct_fragment = f" ({abs_pct:.1f}% {direction} average)"

    return (
        f"Over the last {period_weeks} weeks you are averaging "
        f"${driver_avg:.2f}/week — ${abs_diff:.2f} {direction} the platform "
        f"average of ${platform_avg:.2f}/week{pct_fragment}. "
        f"You rank #{rank} out of {total_drivers} active driver(s) "
        f"({percentile:.1f}th percentile)."
    )


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #


async def get_driver_earnings_comparison(
    db: AsyncSession,
    driver_id: int,
) -> DriverEarningsComparison:
    """Build and return an earnings comparison for the given driver.

    Executes a single aggregating DB query (completed rides in the last
    COMPARISON_WEEKS weeks grouped by driver_id).  All ranking and note
    generation runs in Python for full testability without a live database.
    """
    now = _utc_now()
    window_start = now - timedelta(weeks=COMPARISON_WEEKS)

    # Single aggregating query — total fare and ride count per driver
    result = await db.execute(
        select(
            Ride.driver_id,
            func.coalesce(func.sum(Ride.actual_fare), 0.0).label("total_fare"),
            func.count().label("ride_count"),
        ).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.requested_at >= window_start,
        ).group_by(Ride.driver_id)
    )
    rows = result.all()  # list of Row(driver_id, total_fare, ride_count)

    # Build per-driver avg weekly earnings map
    driver_totals: dict[int, float] = {}
    for row in rows:
        driver_totals[row.driver_id] = (row.total_fare or 0.0) / COMPARISON_WEEKS

    # Current driver's avg (may be 0 if they had no rides)
    driver_avg = round(driver_totals.get(driver_id, 0.0), 2)

    # If the current driver had no rides, include them with avg=0 for ranking
    all_avgs = list(driver_totals.values())
    if driver_id not in driver_totals:
        all_avgs.append(0.0)

    active_drivers = len(driver_totals)  # only drivers with ≥1 completed ride
    all_avgs_rounded = [round(avg, 2) for avg in all_avgs]

    # Platform average across all active drivers (excluding zero-ride drivers)
    if active_drivers > 0:
        platform_avg = round(
            sum(driver_totals.values()) / active_drivers, 2
        )
    else:
        platform_avg = 0.0

    difference_usd = round(driver_avg - platform_avg, 2)
    difference_pct = _compute_difference_pct(driver_avg, platform_avg)

    percentile_obj = _compute_percentile(driver_avg, all_avgs_rounded)

    note = _build_comparison_note(
        driver_avg=driver_avg,
        platform_avg=platform_avg,
        difference_usd=difference_usd,
        difference_pct=difference_pct,
        rank=percentile_obj.rank,
        total_drivers=percentile_obj.total_drivers,
        percentile=percentile_obj.percentile,
        period_weeks=COMPARISON_WEEKS,
    )

    return DriverEarningsComparison(
        as_of=now,
        period_weeks=COMPARISON_WEEKS,
        driver_avg_weekly_usd=driver_avg,
        platform_avg_weekly_usd=platform_avg,
        difference_usd=difference_usd,
        difference_pct=difference_pct,
        percentile=percentile_obj,
        active_drivers_in_period=active_drivers,
        comparison_note=note,
    )
