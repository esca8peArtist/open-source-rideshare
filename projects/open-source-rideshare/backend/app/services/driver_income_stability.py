"""Driver income stability report service.

Computes a 12-week retrospective of a driver's weekly earnings variance and
surfaces it as a structured report via GET /drivers/me/income-stability-report.

Gig platforms like Uber and Lyft are structurally indifferent to driver income
instability — their business model thrives on flexible labor supply regardless
of driver financial outcomes.  A driver-owned cooperative has an obligation to
quantify and address income volatility, because unpredictable earnings harm
members' financial wellbeing.  This service surfaces a 12-week retrospective
of a driver's earnings variance to help them understand their income stability
and plan accordingly.  It also acknowledges when the platform's earnings
guarantee (if active) helped smooth income.

Public API:
    get_driver_income_stability_report(db, driver_id) → DriverIncomeStabilityReport
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_earnings_guarantee import GuaranteeStatus, WeeklyGuaranteeRecord
from app.models.ride import Ride, RideStatus
from app.schemas.driver_income_stability import (
    DriverIncomeStabilityReport,
    WeeklyEarningsEntry,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PERIOD_WEEKS: int = 12
_TREND_THRESHOLD_PCT: float = 0.10  # 10% change triggers improving/declining


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso_week_monday(d: date) -> date:
    """Return the Monday of the ISO week containing date d."""
    return d - timedelta(days=d.weekday())


def _build_week_windows(today: date, n_weeks: int) -> list[tuple[date, date]]:
    """Return a list of (week_start, week_end) tuples, newest-first.

    Each tuple spans Monday–Sunday of one ISO calendar week.
    The most recent entry is the current (possibly partial) week.
    """
    current_monday = _iso_week_monday(today)
    windows: list[tuple[date, date]] = []
    for i in range(n_weeks):
        week_start = current_monday - timedelta(weeks=i)
        week_end = week_start + timedelta(days=6)
        windows.append((week_start, week_end))
    return windows  # newest first


def _compute_std_dev(values: list[float]) -> Optional[float]:
    """Population standard deviation, or None if fewer than 2 values."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _stability_tier(cv: Optional[float], weeks_analyzed: int) -> str:
    if weeks_analyzed < 2:
        return "insufficient_data"
    if cv is None:
        return "insufficient_data"
    if cv < 0.2:
        return "high"
    if cv <= 0.4:
        return "moderate"
    return "low"


def _trend_direction(weekly_breakdown: list[WeeklyEarningsEntry]) -> str:
    """Derive trend from first-4 vs last-4 weeks among the 12-week window.

    weekly_breakdown is already sorted newest-first, so:
      - "last 4 weeks"  = indices 0–3  (most recent)
      - "first 4 weeks" = indices 8–11 (oldest)
    """
    if len(weekly_breakdown) < 12:
        return "insufficient_data"

    # Use only weeks that had rides for comparison; but we need positional
    # averages over the actual first/last 4 slots (including zeros) to avoid
    # artificially inflating "improving" for drivers returning from leave.
    recent_4 = [e.earnings_usd for e in weekly_breakdown[:4]]
    oldest_4 = [e.earnings_usd for e in weekly_breakdown[8:12]]

    recent_avg = sum(recent_4) / 4
    oldest_avg = sum(oldest_4) / 4

    # If both windows are all-zero there is no meaningful trend.
    if oldest_avg == 0 and recent_avg == 0:
        return "insufficient_data"

    if oldest_avg == 0:
        # Driver wasn't active in the old window but is now — improving.
        return "improving"

    change = (recent_avg - oldest_avg) / oldest_avg
    if change > _TREND_THRESHOLD_PCT:
        return "improving"
    if change < -_TREND_THRESHOLD_PCT:
        return "declining"
    return "stable"


def _build_stability_note(tier: str, trend: str) -> str:
    """Compose a single human-readable sentence describing stability and trend."""
    tier_phrases = {
        "high": "Your income is highly stable",
        "moderate": "Your income is moderately stable",
        "low": "Your income has been quite volatile",
        "insufficient_data": "There is not yet enough data to assess your income stability",
    }
    trend_phrases = {
        "improving": "with an upward trend",
        "declining": "with a downward trend",
        "stable": "and has remained steady",
        "insufficient_data": "",
    }

    tier_text = tier_phrases.get(tier, "Your income stability is unclear")
    trend_text = trend_phrases.get(trend, "")

    if tier == "insufficient_data":
        return f"{tier_text} over the past 12 weeks — keep driving to unlock your full report."

    if trend_text:
        # For "stable" trend, join differently to read naturally.
        if trend == "stable":
            return f"{tier_text} {trend_text} over the past 12 weeks."
        return f"{tier_text} {trend_text} over the past 12 weeks."

    return f"{tier_text} over the past 12 weeks."


# ---------------------------------------------------------------------------
# Database fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_completed_rides(
    db: AsyncSession,
    driver_id: int,
    window_start: datetime,
    window_end: datetime,
) -> list[Ride]:
    """Return completed rides for the driver within the datetime window."""
    result = await db.execute(
        select(Ride).where(
            and_(
                Ride.driver_id == driver_id,
                Ride.status == RideStatus.COMPLETED,
                Ride.completed_at >= window_start,
                Ride.completed_at <= window_end,
            )
        )
    )
    return list(result.scalars().all())


async def _fetch_guarantee_records(
    db: AsyncSession,
    driver_id: int,
    week_starts: list[date],
) -> set[date]:
    """Return the set of week_start dates where a guarantee payout was made.

    Looks for WeeklyGuaranteeRecord rows with status=paid for this driver.
    Returns an empty set if no guarantee records exist (graceful degradation).
    """
    if not week_starts:
        return set()
    try:
        result = await db.execute(
            select(WeeklyGuaranteeRecord.week_start).where(
                and_(
                    WeeklyGuaranteeRecord.driver_id == driver_id,
                    WeeklyGuaranteeRecord.week_start.in_(week_starts),
                    WeeklyGuaranteeRecord.status == GuaranteeStatus.paid,
                )
            )
        )
        return {row[0] for row in result}
    except Exception:
        logger.warning(
            "Could not query guarantee records for driver %d; defaulting to 0.",
            driver_id,
            exc_info=True,
        )
        return set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_driver_income_stability_report(
    db: AsyncSession,
    driver_id: int,
) -> DriverIncomeStabilityReport:
    """Compute a 12-week income stability report for driver_id.

    Args:
        db:         Async database session.
        driver_id:  ID of the authenticated driver (User.id).

    Returns:
        DriverIncomeStabilityReport with variance metrics, trend direction,
        weekly breakdown, and a plain-language stability note.
    """
    now = _utc_now()
    today = now.date()

    # Build the 12 ISO-week windows (newest-first)
    windows = _build_week_windows(today, _PERIOD_WEEKS)

    # Determine the overall query window
    oldest_start = windows[-1][0]  # Monday of oldest week
    newest_end = windows[0][1]     # Sunday of newest (current) week

    window_start_dt = datetime(
        oldest_start.year, oldest_start.month, oldest_start.day,
        0, 0, 0, tzinfo=timezone.utc,
    )
    window_end_dt = datetime(
        newest_end.year, newest_end.month, newest_end.day,
        23, 59, 59, tzinfo=timezone.utc,
    )

    # Fetch all relevant completed rides in one query
    all_rides = await _fetch_completed_rides(db, driver_id, window_start_dt, window_end_dt)

    # Build a lookup: ISO week_start → list of rides
    rides_by_week: dict[date, list[Ride]] = {ws: [] for ws, _ in windows}
    for ride in all_rides:
        if ride.completed_at is None:
            continue
        ride_date = ride.completed_at.date()
        monday = _iso_week_monday(ride_date)
        if monday in rides_by_week:
            rides_by_week[monday].append(ride)

    # Fetch guarantee payout records
    week_starts = [ws for ws, _ in windows]
    guarantee_paid_weeks = await _fetch_guarantee_records(db, driver_id, week_starts)

    # Build weekly breakdown (newest-first)
    weekly_breakdown: list[WeeklyEarningsEntry] = []
    for week_start, week_end in windows:
        week_rides = rides_by_week.get(week_start, [])
        earnings = sum(
            (r.actual_fare or 0.0) + (r.tip_amount or 0.0)
            for r in week_rides
        )
        weekly_breakdown.append(
            WeeklyEarningsEntry(
                week_start=week_start,
                week_end=week_end,
                earnings_usd=round(earnings, 2),
                ride_count=len(week_rides),
                had_guarantee_payout=week_start in guarantee_paid_weeks,
            )
        )

    # Derive aggregate statistics
    active_entries = [e for e in weekly_breakdown if e.earnings_usd > 0]
    weeks_analyzed = len(active_entries)
    weeks_inactive = _PERIOD_WEEKS - weeks_analyzed
    guarantee_activations = sum(1 for e in weekly_breakdown if e.had_guarantee_payout)

    active_earnings = [e.earnings_usd for e in active_entries]

    mean_weekly: Optional[float] = None
    std_dev: Optional[float] = None
    cv: Optional[float] = None
    best_week: Optional[float] = None
    worst_nonzero_week: Optional[float] = None

    if weeks_analyzed > 0:
        mean_weekly = round(sum(active_earnings) / weeks_analyzed, 2)
        best_week = round(max(active_earnings), 2)
        worst_nonzero_week = round(min(active_earnings), 2)

    if weeks_analyzed >= 2:
        std_dev_raw = _compute_std_dev(active_earnings)
        if std_dev_raw is not None:
            std_dev = round(std_dev_raw, 2)
            if mean_weekly and mean_weekly > 0:
                cv = round(std_dev_raw / mean_weekly, 4)

    tier = _stability_tier(cv, weeks_analyzed)
    trend = _trend_direction(weekly_breakdown)
    note = _build_stability_note(tier, trend)

    return DriverIncomeStabilityReport(
        period_weeks=_PERIOD_WEEKS,
        weeks_analyzed=weeks_analyzed,
        weeks_inactive=weeks_inactive,
        mean_weekly_earnings_usd=mean_weekly,
        std_dev_weekly_earnings_usd=std_dev,
        coefficient_of_variation=cv,
        stability_tier=tier,
        trend_direction=trend,
        best_week_earnings_usd=best_week,
        worst_nonzero_week_earnings_usd=worst_nonzero_week,
        guarantee_activations=guarantee_activations,
        weekly_breakdown=weekly_breakdown,
        stability_note=note,
    )
