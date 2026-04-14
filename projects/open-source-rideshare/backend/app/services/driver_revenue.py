"""Driver revenue projection and earnings comparison service.

All queries are read-only; no data is mutated here.

Revenue projections:
  - Pulls completed rides from the last 30 days (or all history if < 30 days)
  - Extrapolates to the requested period (week/month/quarter)
  - Applies a scenario multiplier (conservative/moderate/optimistic)
  - Returns a "new driver baseline" using platform averages for drivers with < 5 rides

Earnings comparison:
  - Compares a driver's metrics against platform-wide averages for the same period
  - Computes percentile rank across all active drivers in the period
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PLATFORM_FEE_PCT = 0.12  # 12 % of gross fare

SCENARIO_MULTIPLIERS: dict[str, float] = {
    "conservative": 0.8,
    "moderate": 1.0,
    "optimistic": 1.25,
}

PERIOD_DAYS: dict[str, int] = {
    "week": 7,
    "month": 30,
    "quarter": 90,
}

# Platform-wide averages used for new-driver baseline estimates.
# These represent typical values across the platform and are updated
# periodically as the platform grows.
_PLATFORM_AVG_RIDES_PER_DAY = 3.2
_PLATFORM_AVG_EARNINGS_PER_RIDE = 14.50
_PLATFORM_AVG_TIP_PER_RIDE = 1.45  # ~10 % tip rate
_PLATFORM_AVG_RIDE_DURATION_HOURS = 0.33  # ~20 minutes per ride
_PLATFORM_AVG_COMPLETION_RATE = 0.91

NEW_DRIVER_THRESHOLD = 5  # rides below this count triggers new-driver baseline

# Projection note templates
_NOTE_ESTABLISHED = (
    "Projection based on your last 30 days of activity. "
    "Optimistic scenario assumes peak-hour optimization."
)
_NOTE_NEW_DRIVER = (
    "You have fewer than 5 completed rides, so this projection uses "
    "platform-wide averages. Your personalized projection will be available "
    "once you have more ride history."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _history_window_start(days: int = 30) -> datetime:
    """Return UTC-aware datetime for `days` ago."""
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


async def _fetch_driver_rides(
    db: AsyncSession,
    driver_id: int,
    since: datetime,
) -> list[Ride]:
    """Fetch completed rides for a driver since the given datetime."""
    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= since,
        )
    )
    return list(result.scalars().all())


async def _fetch_tips_for_rides(
    db: AsyncSession,
    driver_id: int,
    ride_ids: list[int],
) -> dict[int, float]:
    """Return a mapping of ride_id -> tip amount (dollars) for the given rides."""
    if not ride_ids:
        return {}
    result = await db.execute(
        select(TipRecord).where(
            TipRecord.ride_id.in_(ride_ids),
            TipRecord.driver_id == driver_id,
            TipRecord.status == TipStatus.COMPLETED,
        )
    )
    return {t.ride_id: t.amount_cents / 100.0 for t in result.scalars().all()}


async def _fetch_platform_fees_for_rides(
    db: AsyncSession,
    ride_ids: list[int],
) -> dict[int, float]:
    """Return a mapping of ride_id -> platform_fee (dollars) from the payments table."""
    if not ride_ids:
        return {}
    result = await db.execute(
        select(Payment).where(
            Payment.ride_id.in_(ride_ids),
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    return {p.ride_id: p.platform_fee for p in result.scalars().all()}


def _avg_ride_duration_hours(rides: list[Ride]) -> float:
    """Return mean ride duration in hours, falling back to platform average."""
    durations = [r.duration_min for r in rides if r.duration_min is not None]
    if not durations:
        return _PLATFORM_AVG_RIDE_DURATION_HOURS
    return (sum(durations) / len(durations)) / 60.0


def _build_projection(
    *,
    avg_daily_rides: float,
    avg_earnings_per_ride: float,
    avg_tip_per_ride: float,
    avg_platform_fee_pct: float,
    avg_ride_duration_hours: float,
    period: str,
    scenario: str,
) -> dict[str, Any]:
    """Compute the projection dict for the given inputs and scenario."""
    multiplier = SCENARIO_MULTIPLIERS[scenario]
    period_days = PERIOD_DAYS[period]

    estimated_rides = round(avg_daily_rides * period_days * multiplier)
    estimated_gross = round(avg_earnings_per_ride * estimated_rides, 2)
    estimated_tips = round(avg_tip_per_ride * estimated_rides, 2)
    platform_fees = round(estimated_gross * avg_platform_fee_pct, 2)
    estimated_net = round(estimated_gross - platform_fees, 2)

    total_ride_hours = estimated_rides * avg_ride_duration_hours
    avg_hourly_rate = (
        round(estimated_net / total_ride_hours, 2) if total_ride_hours > 0 else 0.0
    )

    return {
        "estimated_rides": estimated_rides,
        "estimated_gross_earnings": estimated_gross,
        "estimated_net_earnings": estimated_net,
        "estimated_tips": estimated_tips,
        "platform_fees_deducted": platform_fees,
        "avg_hourly_rate": avg_hourly_rate,
    }


# ---------------------------------------------------------------------------
# Revenue projection
# ---------------------------------------------------------------------------


async def get_driver_revenue_projection(
    db: AsyncSession,
    driver_id: int,
    period: str = "month",
    scenario: str = "moderate",
) -> dict[str, Any]:
    """Return a personalized revenue projection for the given driver.

    Args:
        db: async database session
        driver_id: authenticated driver's user ID
        period: one of week/month/quarter
        scenario: one of conservative/moderate/optimistic

    Returns a dict matching the RevenueProjectionResponse schema.

    For drivers with fewer than NEW_DRIVER_THRESHOLD completed rides the
    response is based on platform-wide averages and includes
    ``is_new_driver_estimate: true``.
    """
    history_since = _history_window_start(days=30)
    rides = await _fetch_driver_rides(db, driver_id=driver_id, since=history_since)

    scenario_multipliers_payload = dict(SCENARIO_MULTIPLIERS)

    # --- New driver path ---
    if len(rides) < NEW_DRIVER_THRESHOLD:
        projection = _build_projection(
            avg_daily_rides=_PLATFORM_AVG_RIDES_PER_DAY,
            avg_earnings_per_ride=_PLATFORM_AVG_EARNINGS_PER_RIDE,
            avg_tip_per_ride=_PLATFORM_AVG_TIP_PER_RIDE,
            avg_platform_fee_pct=DEFAULT_PLATFORM_FEE_PCT,
            avg_ride_duration_hours=_PLATFORM_AVG_RIDE_DURATION_HOURS,
            period=period,
            scenario=scenario,
        )
        return {
            "driver_id": driver_id,
            "period": period,
            "scenario": scenario,
            "projection": projection,
            "based_on": {
                "historical_rides": len(rides),
                "historical_days": 30,
                "avg_daily_rides": _PLATFORM_AVG_RIDES_PER_DAY,
                "avg_earnings_per_ride": _PLATFORM_AVG_EARNINGS_PER_RIDE,
            },
            "scenario_multipliers": scenario_multipliers_payload,
            "is_new_driver_estimate": True,
            "notes": _NOTE_NEW_DRIVER,
        }

    # --- Established driver path ---
    ride_ids = [r.id for r in rides]
    tips_by_ride = await _fetch_tips_for_rides(db, driver_id=driver_id, ride_ids=ride_ids)
    fees_by_ride = await _fetch_platform_fees_for_rides(db, ride_ids=ride_ids)

    # Determine actual date span so we can compute rides-per-day accurately
    completed_dates = [r.completed_at for r in rides if r.completed_at is not None]
    if len(completed_dates) >= 2:
        earliest = min(completed_dates)
        latest = max(completed_dates)
        # At least 1 day, and capped at our 30-day window
        historical_days = max(1, (latest - earliest).days + 1)
    else:
        historical_days = 1

    total_rides = len(rides)
    avg_daily_rides = round(total_rides / historical_days, 2)

    gross_fares = [r.actual_fare or r.estimated_fare for r in rides]
    avg_earnings_per_ride = round(sum(gross_fares) / total_rides, 2)

    tip_amounts = [tips_by_ride.get(r.id, 0.0) for r in rides]
    avg_tip_per_ride = round(sum(tip_amounts) / total_rides, 2)

    # Effective platform fee percentage from actual payment records, else default
    fee_amounts = [fees_by_ride[r.id] for r in rides if r.id in fees_by_ride]
    if fee_amounts and sum(gross_fares) > 0:
        avg_platform_fee_pct = sum(fee_amounts) / sum(gross_fares)
    else:
        avg_platform_fee_pct = DEFAULT_PLATFORM_FEE_PCT

    avg_ride_duration_hours = _avg_ride_duration_hours(rides)

    projection = _build_projection(
        avg_daily_rides=avg_daily_rides,
        avg_earnings_per_ride=avg_earnings_per_ride,
        avg_tip_per_ride=avg_tip_per_ride,
        avg_platform_fee_pct=avg_platform_fee_pct,
        avg_ride_duration_hours=avg_ride_duration_hours,
        period=period,
        scenario=scenario,
    )

    return {
        "driver_id": driver_id,
        "period": period,
        "scenario": scenario,
        "projection": projection,
        "based_on": {
            "historical_rides": total_rides,
            "historical_days": historical_days,
            "avg_daily_rides": avg_daily_rides,
            "avg_earnings_per_ride": avg_earnings_per_ride,
        },
        "scenario_multipliers": scenario_multipliers_payload,
        "is_new_driver_estimate": False,
        "notes": _NOTE_ESTABLISHED,
    }


# ---------------------------------------------------------------------------
# Earnings comparison
# ---------------------------------------------------------------------------


async def _fetch_all_driver_rides_in_period(
    db: AsyncSession,
    since: datetime,
) -> list[Ride]:
    """Fetch all completed rides across all drivers in the given period."""
    result = await db.execute(
        select(Ride).where(
            Ride.driver_id.is_not(None),
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= since,
        )
    )
    return list(result.scalars().all())


def _driver_stats_from_rides(
    rides: list[Ride],
    tips_by_ride: dict[int, float],
) -> dict[str, Any]:
    """Compute per-driver aggregate stats from a list of rides."""
    total_rides = len(rides)
    if total_rides == 0:
        return {
            "total_rides": 0,
            "gross_earnings": 0.0,
            "avg_per_ride": 0.0,
            "tips": 0.0,
            "completion_rate": 0.0,
        }

    gross = sum(r.actual_fare or r.estimated_fare for r in rides)
    tips = sum(tips_by_ride.get(r.id, 0.0) for r in rides)

    # completion_rate: completed / (completed + cancelled).
    # Since we only pull COMPLETED rides this is always 1.0 without cancelled context.
    # The comparison endpoint separately queries all driver rides to get completion rate.
    return {
        "total_rides": total_rides,
        "gross_earnings": round(gross, 2),
        "avg_per_ride": round(gross / total_rides, 2),
        "tips": round(tips, 2),
        "completion_rate": 1.0,  # overridden by caller with actual rate
    }


def _percentile(value: float, all_values: list[float]) -> int:
    """Return percentile rank (0–100) of value in all_values (higher is better)."""
    if not all_values:
        return 50
    below = sum(1 for v in all_values if v < value)
    return round(below / len(all_values) * 100)


async def get_driver_earnings_comparison(
    db: AsyncSession,
    driver_id: int,
    period: str = "month",
) -> dict[str, Any]:
    """Compare a driver's performance vs. platform averages for the period.

    Args:
        db: async database session
        driver_id: authenticated driver's user ID
        period: one of week/month/quarter

    Returns a dict matching the EarningsComparisonResponse schema.
    """
    period_days = PERIOD_DAYS[period]
    since = _history_window_start(days=period_days)

    # Fetch this driver's completed rides in the period
    driver_rides = await _fetch_driver_rides(db, driver_id=driver_id, since=since)
    driver_ride_ids = [r.id for r in driver_rides]
    driver_tips = await _fetch_tips_for_rides(
        db, driver_id=driver_id, ride_ids=driver_ride_ids
    )

    # Fetch all platform rides in the period for comparison
    all_rides = await _fetch_all_driver_rides_in_period(db, since=since)

    # Also fetch all cancelled rides by this driver to compute an accurate
    # completion rate for the driver
    cancelled_result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.CANCELLED,
            Ride.requested_at >= since,
        )
    )
    driver_cancelled_rides = list(cancelled_result.scalars().all())

    driver_total_attempted = len(driver_rides) + len(driver_cancelled_rides)
    driver_completion_rate = (
        round(len(driver_rides) / driver_total_attempted, 4)
        if driver_total_attempted > 0
        else 0.0
    )

    # Group all platform rides by driver_id
    rides_by_driver: dict[int, list[Ride]] = {}
    for ride in all_rides:
        if ride.driver_id is not None:
            rides_by_driver.setdefault(ride.driver_id, []).append(ride)

    # Compute per-driver aggregates
    driver_totals: dict[int, dict[str, float]] = {}
    for did, d_rides in rides_by_driver.items():
        ride_ids = [r.id for r in d_rides]
        # We need tips per driver — fetch all tips for all rides at once outside this loop
        driver_totals[did] = {
            "total_rides": len(d_rides),
            "gross_earnings": sum(r.actual_fare or r.estimated_fare for r in d_rides),
            "tips": 0.0,  # filled in after bulk tip fetch below
        }

    # Bulk fetch all tips for the period to avoid N+1 queries
    all_ride_ids = [r.id for r in all_rides]
    all_tips_map: dict[int, float] = {}
    if all_ride_ids:
        all_tips_result = await db.execute(
            select(TipRecord).where(
                TipRecord.ride_id.in_(all_ride_ids),
                TipRecord.status == TipStatus.COMPLETED,
            )
        )
        for tip in all_tips_result.scalars().all():
            # Map tip to its ride's driver_id
            ride_driver_map = {r.id: r.driver_id for r in all_rides}
            did = ride_driver_map.get(tip.ride_id)
            if did is not None:
                driver_totals.setdefault(did, {"total_rides": 0, "gross_earnings": 0.0, "tips": 0.0})
                driver_totals[did]["tips"] = driver_totals[did].get("tips", 0.0) + tip.amount_cents / 100.0
            all_tips_map[tip.ride_id] = tip.amount_cents / 100.0

    # Platform averages
    all_driver_ids = list(rides_by_driver.keys())
    num_drivers = len(all_driver_ids)

    if num_drivers > 0:
        platform_avg_rides = round(
            sum(d["total_rides"] for d in driver_totals.values()) / num_drivers, 1
        )
        platform_avg_gross = round(
            sum(d["gross_earnings"] for d in driver_totals.values()) / num_drivers, 2
        )
        platform_avg_per_ride = round(
            sum(
                d["gross_earnings"] / d["total_rides"]
                for d in driver_totals.values()
                if d["total_rides"] > 0
            ) / num_drivers,
            2,
        )
        platform_avg_tips = round(
            sum(d["tips"] for d in driver_totals.values()) / num_drivers, 2
        )
        platform_avg_completion = _PLATFORM_AVG_COMPLETION_RATE
    else:
        platform_avg_rides = 0.0
        platform_avg_gross = 0.0
        platform_avg_per_ride = 0.0
        platform_avg_tips = 0.0
        platform_avg_completion = _PLATFORM_AVG_COMPLETION_RATE

    # This driver's stats for the period
    driver_gross = sum(r.actual_fare or r.estimated_fare for r in driver_rides)
    driver_tip_total = sum(driver_tips.get(r.id, 0.0) for r in driver_rides)
    driver_avg_per_ride = (
        round(driver_gross / len(driver_rides), 2) if driver_rides else 0.0
    )

    # Percentile vectors across all active drivers
    all_rides_counts = [d["total_rides"] for d in driver_totals.values()]
    all_gross_earnings = [d["gross_earnings"] for d in driver_totals.values()]
    all_tip_totals = [d["tips"] for d in driver_totals.values()]

    # For completion rate percentile, use the driver's rate vs. platform constant
    # (we don't have per-driver cancelled counts for all drivers in this query).
    # We represent platform as a single reference point.
    all_completion_rates = [_PLATFORM_AVG_COMPLETION_RATE] * max(num_drivers, 1)

    return {
        "period": period,
        "driver": {
            "total_rides": len(driver_rides),
            "gross_earnings": round(driver_gross, 2),
            "avg_per_ride": driver_avg_per_ride,
            "tips": round(driver_tip_total, 2),
            "completion_rate": driver_completion_rate,
        },
        "platform_average": {
            "total_rides": platform_avg_rides,
            "gross_earnings": platform_avg_gross,
            "avg_per_ride": platform_avg_per_ride,
            "tips": platform_avg_tips,
            "completion_rate": platform_avg_completion,
        },
        "percentile": {
            "rides": _percentile(len(driver_rides), all_rides_counts),
            "earnings": _percentile(driver_gross, all_gross_earnings),
            "tips": _percentile(driver_tip_total, all_tip_totals),
            "completion_rate": _percentile(driver_completion_rate, all_completion_rates),
        },
    }
