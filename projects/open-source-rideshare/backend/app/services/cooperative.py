"""Cooperative transparency and member equity services.

Provides:
  - Platform-wide public stats (live)
  - Driver cooperative equity profile
  - Quarterly transparency report generation and retrieval

This is the financial backbone of the cooperative model: every member can
see exactly how money flows through the platform — what percent goes to
drivers, what the platform retains, and how the cooperative is performing.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cooperative_report import CooperativeReport
from app.models.driver import DriverProfile
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quarter_date_range(year: int, quarter: int) -> tuple[date, date]:
    """Return (start_date, end_date) for a calendar quarter (inclusive)."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"Quarter must be 1–4, got {quarter}")
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    start = date(year, start_month, 1)
    # Last day of end_month
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1).replace(day=1)
        # subtract one day
        from datetime import timedelta
        end = end - timedelta(days=1)
    return start, end


# ---------------------------------------------------------------------------
# Public platform stats
# ---------------------------------------------------------------------------

async def get_platform_public_stats(db: AsyncSession) -> dict:
    """Live, all-time aggregate stats visible to any visitor.

    Returns totals since platform inception — not filtered by period.
    """
    # Completed rides
    completed = await db.execute(
        select(func.count(Ride.id)).where(Ride.status == RideStatus.COMPLETED)
    )
    total_completed = completed.scalar_one() or 0

    cancelled = await db.execute(
        select(func.count(Ride.id)).where(Ride.status == RideStatus.CANCELLED)
    )
    total_cancelled = cancelled.scalar_one() or 0

    # Financial totals from completed ride_fare payments
    fin = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount), 0.0),
            func.coalesce(func.sum(Payment.platform_fee), 0.0),
            func.coalesce(func.sum(Payment.tip_amount), 0.0),
        ).where(
            Payment.payment_type == PaymentType.RIDE_FARE,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    total_fare, total_platform_fee, total_tips = fin.one()

    total_driver_earnings = float(total_fare) - float(total_platform_fee)
    platform_fee_rate = (
        round(float(total_platform_fee) / float(total_fare) * 100, 2)
        if total_fare
        else 0.0
    )
    driver_take_rate = (
        round(total_driver_earnings / float(total_fare) * 100, 2)
        if total_fare
        else 0.0
    )

    # Member counts
    total_drivers = await db.execute(
        select(func.count(DriverProfile.id)).where(DriverProfile.is_approved.is_(True))
    )
    total_riders = await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.RIDER, User.is_active.is_(True))
    )
    online_drivers = await db.execute(
        select(func.count(DriverProfile.id)).where(
            DriverProfile.is_online.is_(True), DriverProfile.is_approved.is_(True)
        )
    )

    return {
        "total_completed_rides": total_completed,
        "total_cancelled_rides": total_cancelled,
        "total_fare_collected_usd": round(float(total_fare), 2),
        "total_platform_fees_usd": round(float(total_platform_fee), 2),
        "total_driver_earnings_usd": round(total_driver_earnings, 2),
        "total_tips_usd": round(float(total_tips), 2),
        "platform_fee_rate_pct": platform_fee_rate,
        "driver_take_rate_pct": driver_take_rate,
        "total_approved_drivers": total_drivers.scalar_one() or 0,
        "total_active_riders": total_riders.scalar_one() or 0,
        "drivers_currently_online": online_drivers.scalar_one() or 0,
    }


# ---------------------------------------------------------------------------
# Driver equity profile
# ---------------------------------------------------------------------------

async def get_driver_equity_stats(db: AsyncSession, driver_profile_id: int) -> dict | None:
    """A driver's cooperative equity profile.

    Equity share is estimated as:
        driver's lifetime trips / total platform trips * 100

    This is a simple proxy — in a formal cooperative structure, equity would be
    tracked via share certificates, but this gives the spirit of contribution-
    weighted membership.

    Returns None if the driver profile is not found.
    """
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        return None

    user_result = await db.execute(select(User).where(User.id == driver.user_id))
    user = user_result.scalar_one_or_none()

    # Platform totals for share calculation
    total_completed = await db.execute(
        select(func.count(Ride.id)).where(Ride.status == RideStatus.COMPLETED)
    )
    platform_total_trips = total_completed.scalar_one() or 0

    # Driver's completed rides (as driver)
    driver_rides = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.driver_id == driver.user_id,
            Ride.status == RideStatus.COMPLETED,
        )
    )
    driver_completed = driver_rides.scalar_one() or 0

    # Driver's financial contribution
    earnings_result = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount - Payment.platform_fee), 0.0),
            func.coalesce(func.sum(Payment.platform_fee), 0.0),
            func.coalesce(func.sum(Payment.tip_amount), 0.0),
        )
        .join(Ride, Payment.ride_id == Ride.id)
        .where(
            Ride.driver_id == driver.user_id,
            Payment.payment_type == PaymentType.RIDE_FARE,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    driver_earnings, platform_contributed, tips_received = earnings_result.one()

    # Tenure
    now = datetime.now(timezone.utc)
    member_since = driver.created_at
    tenure_days = (now - member_since).days if member_since else 0

    # Equity share pct
    equity_share_pct = (
        round(driver_completed / platform_total_trips * 100, 4)
        if platform_total_trips > 0
        else 0.0
    )

    return {
        "driver_profile_id": driver_profile_id,
        "driver_name": user.name if user else None,
        "member_since": member_since.isoformat() if member_since else None,
        "tenure_days": tenure_days,
        "lifetime_completed_trips": driver_completed,
        "platform_total_trips": platform_total_trips,
        "equity_share_pct": equity_share_pct,
        "lifetime_earnings_usd": round(float(driver_earnings), 2),
        "lifetime_tips_usd": round(float(tips_received), 2),
        "lifetime_platform_contribution_usd": round(float(platform_contributed), 2),
        "rating_avg": driver.rating_avg,
        "is_approved": driver.is_approved,
    }


# ---------------------------------------------------------------------------
# Quarterly transparency reports
# ---------------------------------------------------------------------------

async def generate_quarterly_report(
    db: AsyncSession,
    year: int,
    quarter: int,
    notes: str | None = None,
) -> CooperativeReport:
    """Compute and persist (or refresh) a quarterly transparency report.

    Idempotent: calling twice for the same period refreshes the numbers.
    """
    start_date, end_date = _quarter_date_range(year, quarter)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)

    # Rides in period
    completed = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
        )
    )
    total_rides = completed.scalar_one() or 0

    cancelled = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= start_dt,
            Ride.cancelled_at <= end_dt,
        )
    )
    total_cancelled = cancelled.scalar_one() or 0

    # Payments in period
    fin = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount), 0.0),
            func.coalesce(func.sum(Payment.platform_fee), 0.0),
            func.coalesce(func.sum(Payment.tip_amount), 0.0),
        )
        .join(Ride, Payment.ride_id == Ride.id)
        .where(
            Payment.payment_type == PaymentType.RIDE_FARE,
            Payment.status == PaymentStatus.COMPLETED,
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
        )
    )
    total_fare, total_platform_fee, total_tips = fin.one()
    total_fare = float(total_fare)
    total_platform_fee = float(total_platform_fee)
    total_driver_earnings = total_fare - total_platform_fee

    platform_fee_rate = round(total_platform_fee / total_fare * 100, 2) if total_fare else 0.0
    driver_take_rate = round(total_driver_earnings / total_fare * 100, 2) if total_fare else 0.0

    # Active drivers/riders in period (anyone who had a ride)
    active_drivers_q = await db.execute(
        select(func.count(func.distinct(Ride.driver_id))).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
            Ride.driver_id.isnot(None),
        )
    )
    active_drivers = active_drivers_q.scalar_one() or 0

    active_riders_q = await db.execute(
        select(func.count(func.distinct(Ride.rider_id))).where(
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
        )
    )
    active_riders = active_riders_q.scalar_one() or 0

    # New members in period
    new_drivers_q = await db.execute(
        select(func.count(DriverProfile.id)).where(
            DriverProfile.created_at >= start_dt,
            DriverProfile.created_at <= end_dt,
        )
    )
    new_drivers = new_drivers_q.scalar_one() or 0

    new_riders_q = await db.execute(
        select(func.count(User.id)).where(
            User.role == UserRole.RIDER,
            User.created_at >= start_dt,
            User.created_at <= end_dt,
        )
    )
    new_riders = new_riders_q.scalar_one() or 0

    # Upsert
    existing_q = await db.execute(
        select(CooperativeReport).where(
            CooperativeReport.year == year,
            CooperativeReport.quarter == quarter,
        )
    )
    report = existing_q.scalar_one_or_none()

    if report is None:
        report = CooperativeReport(year=year, quarter=quarter)
        db.add(report)

    report.total_rides = total_rides
    report.total_cancelled_rides = total_cancelled
    report.total_fare_collected_usd = round(total_fare, 2)
    report.total_platform_fees_usd = round(total_platform_fee, 2)
    report.total_driver_earnings_usd = round(total_driver_earnings, 2)
    report.total_tips_usd = round(float(total_tips), 2)
    report.platform_fee_rate_pct = platform_fee_rate
    report.driver_take_rate_pct = driver_take_rate
    report.active_drivers = active_drivers
    report.active_riders = active_riders
    report.new_drivers = new_drivers
    report.new_riders = new_riders
    if notes is not None:
        report.notes = notes

    await db.flush()
    return report


async def get_quarterly_report(
    db: AsyncSession, year: int, quarter: int
) -> CooperativeReport | None:
    result = await db.execute(
        select(CooperativeReport).where(
            CooperativeReport.year == year,
            CooperativeReport.quarter == quarter,
        )
    )
    return result.scalar_one_or_none()


async def list_quarterly_reports(db: AsyncSession) -> list[CooperativeReport]:
    result = await db.execute(
        select(CooperativeReport).order_by(
            CooperativeReport.year.desc(),
            CooperativeReport.quarter.desc(),
        )
    )
    return list(result.scalars().all())
