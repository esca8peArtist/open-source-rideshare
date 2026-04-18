"""Service layer for driver earnings summary.

Returns a snapshot of a driver's earnings across four time windows:
today, this week (ISO Mon–now), this month (1st–now), and lifetime.
Also computes pending_payout_usd (rides not yet covered by a completed
DriverPayout) and next_payout_date (derived from DriverBankAccount).

Approach
--------
A single DB query fetches all completed rides.  All bucketing and
arithmetic runs in Python for full testability without a live database.

Platform fee arithmetic
-----------------------
actual_fare = net * (1 + pct/100)
→ net = actual_fare / (1 + pct/100)
→ platform_fee = actual_fare - net

This mirrors the formula used in driver_ride_earnings.py.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payout import DriverBankAccount, DriverPayout, PayoutFrequency, PayoutStatus
from app.models.ride import Ride, RideStatus
from app.schemas.driver_earnings_summary import DriverEarningsSummary, EarningsPeriod


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    """Return current UTC time.  Patched by tests for determinism."""
    return datetime.now(tz=timezone.utc)


def _compute_period(
    rides: list[tuple[float, float]],
    platform_fee_percent: float,
) -> EarningsPeriod:
    """Compute aggregated earnings for a list of (actual_fare, tip_amount) tuples.

    Args:
        rides: Each tuple is (actual_fare, tip_amount) for one completed ride.
        platform_fee_percent: Operator-configured fee, e.g. 20.0 means 20%.

    Returns:
        An EarningsPeriod with all monetary values rounded to 2 decimal places.
    """
    if not rides:
        return EarningsPeriod(
            rides_completed=0,
            gross_earnings_usd=0.0,
            platform_fee_usd=0.0,
            net_earnings_usd=0.0,
            tips_usd=0.0,
            total_take_home_usd=0.0,
        )

    pct = float(platform_fee_percent)
    divisor = 1.0 + pct / 100.0

    gross = 0.0
    net = 0.0
    tips = 0.0

    for actual_fare, tip_amount in rides:
        fare = float(actual_fare)
        tip = float(tip_amount)
        gross += fare
        ride_net = fare / divisor if pct > 0 else fare
        net += ride_net
        tips += tip

    gross = round(gross, 2)
    net = round(net, 2)
    platform_fee = round(gross - net, 2)
    tips = round(tips, 2)

    return EarningsPeriod(
        rides_completed=len(rides),
        gross_earnings_usd=gross,
        platform_fee_usd=platform_fee,
        net_earnings_usd=net,
        tips_usd=tips,
        total_take_home_usd=round(net + tips, 2),
    )


def _next_payout_date(frequency: PayoutFrequency, today: date) -> date:
    """Derive the next payout date from a bank account's payout_frequency.

    DAILY   → tomorrow
    WEEKLY  → next Monday (or next week's Monday if today is Monday)
    BIWEEKLY → next-other Monday
    """
    if frequency == PayoutFrequency.DAILY:
        return today + timedelta(days=1)

    # Days until next Monday: weekday() returns 0 for Monday
    days_since_monday = today.weekday()  # 0=Mon, 6=Sun
    days_to_next_monday = 7 - days_since_monday if days_since_monday > 0 else 7
    next_monday = today + timedelta(days=days_to_next_monday)

    if frequency == PayoutFrequency.WEEKLY:
        return next_monday

    # BIWEEKLY: skip one week
    return next_monday + timedelta(weeks=1)


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #


async def get_driver_earnings_summary(
    db: AsyncSession,
    driver_id: int,
    platform_fee_percent: float,
) -> DriverEarningsSummary:
    """Build and return the earnings summary for the given driver.

    Queries all completed rides for the driver, buckets them into time
    windows in Python, computes pending payout, and derives next payout date.

    Args:
        db: Async SQLAlchemy session.
        driver_id: ID of the authenticated driver.
        platform_fee_percent: Current platform fee from get_pricing_params().
    """
    now = _utc_now()

    # Time window boundaries (UTC)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    days_since_monday = now.weekday()  # 0=Monday
    week_start_date = now.date() - timedelta(days=days_since_monday)
    week_start = datetime.combine(week_start_date, time.min, tzinfo=timezone.utc)

    month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=timezone.utc)

    # Fetch all completed rides for this driver (lifetime)
    result = await db.execute(
        select(Ride.actual_fare, Ride.tip_amount, Ride.completed_at).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.actual_fare.is_not(None),
        )
    )
    rows = result.all()

    # Bucket rides by time window
    today_rides: list[tuple[float, float]] = []
    week_rides: list[tuple[float, float]] = []
    month_rides: list[tuple[float, float]] = []
    lifetime_rides: list[tuple[float, float]] = []

    for row in rows:
        fare = float(row.actual_fare or 0.0)
        tip = float(row.tip_amount or 0.0)
        completed = row.completed_at
        if completed is not None and completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)

        lifetime_rides.append((fare, tip))

        if completed is not None:
            if completed >= month_start:
                month_rides.append((fare, tip))
            if completed >= week_start:
                week_rides.append((fare, tip))
            if completed >= today_start:
                today_rides.append((fare, tip))

    # Compute the last completed payout's period_end to determine pending rides
    payout_result = await db.execute(
        select(DriverPayout.period_end).where(
            DriverPayout.driver_id == driver_id,
            DriverPayout.status == PayoutStatus.COMPLETED,
        ).order_by(DriverPayout.period_end.desc()).limit(1)
    )
    last_payout_row = payout_result.scalar_one_or_none()

    # Compute pending payout: rides completed after the last payout's period_end
    pending_rides: list[tuple[float, float]] = []
    for row in rows:
        fare = float(row.actual_fare or 0.0)
        tip = float(row.tip_amount or 0.0)
        completed = row.completed_at
        if completed is not None and completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)

        if last_payout_row is None:
            # No completed payout at all → all rides are pending
            pending_rides.append((fare, tip))
        else:
            period_end_dt = datetime.combine(last_payout_row, time.max, tzinfo=timezone.utc)
            if completed is not None and completed > period_end_dt:
                pending_rides.append((fare, tip))

    pending_period = _compute_period(pending_rides, platform_fee_percent)
    pending_payout_usd = round(pending_period.total_take_home_usd, 2)

    # Determine next payout date from DriverBankAccount
    bank_result = await db.execute(
        select(DriverBankAccount.payout_frequency).where(
            DriverBankAccount.driver_id == driver_id,
            DriverBankAccount.is_active == True,  # noqa: E712
        ).limit(1)
    )
    bank_row = bank_result.scalar_one_or_none()

    next_payout: Optional[date] = None
    if bank_row is not None:
        next_payout = _next_payout_date(bank_row, now.date())

    return DriverEarningsSummary(
        driver_id=driver_id,
        as_of=now,
        today=_compute_period(today_rides, platform_fee_percent),
        this_week=_compute_period(week_rides, platform_fee_percent),
        this_month=_compute_period(month_rides, platform_fee_percent),
        lifetime=_compute_period(lifetime_rides, platform_fee_percent),
        pending_payout_usd=pending_payout_usd,
        next_payout_date=next_payout,
    )
