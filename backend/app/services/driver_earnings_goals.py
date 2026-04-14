"""Driver earnings goals service.

Public API
----------
get_goal(db, driver_profile_id) -> DriverEarningsGoal | None
set_goal(db, driver_profile_id, period_type, target_amount) -> DriverEarningsGoal
delete_goal(db, driver_profile_id) -> bool
get_goal_progress(db, driver_profile_id) -> EarningsGoalProgressResponse | None
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_earnings_goal import DriverEarningsGoal, GoalPeriodType
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.schemas.driver_earnings_goal import EarningsGoalProgressResponse


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------


def _current_period(period_type: GoalPeriodType) -> tuple[date, date]:
    """Return (period_start, period_end) for the current period in UTC."""
    today = datetime.now(tz=timezone.utc).date()
    if period_type == GoalPeriodType.DAILY:
        return today, today
    # Weekly: Monday–Sunday
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _period_elapsed_fraction(period_start: date, period_end: date) -> float:
    """Fraction of the period that has elapsed (0.0–1.0).

    Returns at least a small epsilon so we never divide by zero in the
    on_track calculation at the very start of a period.
    """
    today = datetime.now(tz=timezone.utc).date()
    total_days = (period_end - period_start).days + 1
    elapsed_days = (today - period_start).days + 1  # 1-indexed: first day counts
    return min(elapsed_days / total_days, 1.0)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def get_goal(db: AsyncSession, driver_profile_id: int) -> DriverEarningsGoal | None:
    """Return the driver's current goal or None if unset."""
    result = await db.execute(
        select(DriverEarningsGoal).where(
            DriverEarningsGoal.driver_profile_id == driver_profile_id
        )
    )
    return result.scalar_one_or_none()


async def set_goal(
    db: AsyncSession,
    driver_profile_id: int,
    period_type: GoalPeriodType,
    target_amount: float,
) -> DriverEarningsGoal:
    """Create or update the driver's earnings goal (upsert)."""
    goal = await get_goal(db, driver_profile_id)
    if goal is None:
        goal = DriverEarningsGoal(
            driver_profile_id=driver_profile_id,
            period_type=period_type,
            target_amount=target_amount,
        )
        db.add(goal)
    else:
        goal.period_type = period_type
        goal.target_amount = target_amount
    await db.flush()
    return goal


async def delete_goal(db: AsyncSession, driver_profile_id: int) -> bool:
    """Delete the driver's goal.  Returns True if a goal existed, False otherwise."""
    goal = await get_goal(db, driver_profile_id)
    if goal is None:
        return False
    await db.delete(goal)
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Progress computation
# ---------------------------------------------------------------------------


async def _fetch_period_earnings(
    db: AsyncSession,
    driver_profile_id: int,
    period_start: date,
    period_end: date,
) -> tuple[float, int]:
    """Return (net_earnings, rides_completed) for the driver in [period_start, period_end].

    Net earnings = sum(actual_fare) - sum(platform_fee) + sum(tip).
    All values are derived from completed rides where the driver FK matches
    the driver_profile_id.  Rides without a matching Payment row contribute
    only their fare (no fee deduction).
    """
    start_dt = datetime(
        period_start.year, period_start.month, period_start.day, 0, 0, 0, tzinfo=timezone.utc
    )
    end_dt = datetime(
        period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc
    )

    # Completed rides for this driver in the period
    rides_result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_profile_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
        )
    )
    rides = list(rides_result.scalars().all())
    if not rides:
        return 0.0, 0

    ride_ids = [r.id for r in rides]

    # Platform fees from payments
    pay_result = await db.execute(
        select(Payment).where(
            Payment.ride_id.in_(ride_ids),
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    payments = list(pay_result.scalars().all())
    fees_by_ride: dict[int, float] = {p.ride_id: p.platform_fee for p in payments}

    # Tips
    tip_result = await db.execute(
        select(TipRecord).where(
            TipRecord.ride_id.in_(ride_ids),
            TipRecord.status == TipStatus.PAID,
        )
    )
    tips_by_ride: dict[int, float] = {}
    for tip in tip_result.scalars().all():
        tips_by_ride[tip.ride_id] = tips_by_ride.get(tip.ride_id, 0.0) + tip.amount

    gross = sum(r.actual_fare or r.estimated_fare or 0.0 for r in rides)
    total_fees = sum(fees_by_ride.get(r.id, 0.0) for r in rides)
    total_tips = sum(tips_by_ride.get(r.id, 0.0) for r in rides)
    net = gross - total_fees + total_tips

    return round(net, 2), len(rides)


async def get_goal_progress(
    db: AsyncSession,
    driver_profile_id: int,
) -> EarningsGoalProgressResponse | None:
    """Return the driver's goal with live progress.

    Returns None if the driver has no goal set.
    """
    goal = await get_goal(db, driver_profile_id)
    if goal is None:
        return None

    period_start, period_end = _current_period(goal.period_type)
    current_earnings, rides_completed = await _fetch_period_earnings(
        db, driver_profile_id, period_start, period_end
    )

    target = goal.target_amount
    percentage = min(round(current_earnings / target * 100, 1), 100.0) if target > 0 else 0.0
    remaining = max(round(target - current_earnings, 2), 0.0)

    # on_track: if pace holds will the driver reach the target?
    elapsed_frac = _period_elapsed_fraction(period_start, period_end)
    projected = (current_earnings / elapsed_frac) if elapsed_frac > 0 else 0.0
    on_track = projected >= target

    return EarningsGoalProgressResponse(
        driver_profile_id=driver_profile_id,
        period_type=goal.period_type,
        target_amount=round(target, 2),
        period_start=period_start,
        period_end=period_end,
        current_earnings=current_earnings,
        rides_completed=rides_completed,
        percentage=percentage,
        on_track=on_track,
        remaining=remaining,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
