"""Analytics service — rider spending and driver tax summary.

All queries are read-only; no data is mutated here.

Rider spending:
  - Aggregates completed rides for a given period (week/month/year/all)
  - Joins with tip_records for tip amounts
  - Provides per-ride detail and optional monthly breakdown

Driver tax summary:
  - Annual earnings breakdown for 1099 preparation
  - Includes fares, tips, incentive bonuses, and platform fees
  - Quarterly breakdown
  - NOTE: This is an estimate only — not tax advice.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incentive import DriverIncentiveProgress, ProgressStatus
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus

# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _period_bounds(period: str) -> tuple[datetime, datetime]:
    """Return UTC-aware start/end datetimes for the given period label.

    period must be one of: week, month, year, all.
    'all' returns epoch start through now.
    """
    now = datetime.now(tz=timezone.utc)
    if period == "week":
        monday = now.date() - __import__("datetime").timedelta(days=now.weekday())
        start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    elif period == "month":
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    elif period == "year":
        start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    else:  # all
        start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return start, now


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def _quarter(month: int) -> str:
    return f"Q{(month - 1) // 3 + 1}"


# ---------------------------------------------------------------------------
# Rider spending
# ---------------------------------------------------------------------------


async def get_rider_spending(
    db: AsyncSession,
    rider_id: int,
    period: str = "month",
    limit: int = 20,
) -> dict[str, Any]:
    """Return spending summary for a rider.

    Args:
        db: async database session
        rider_id: authenticated rider's user ID
        period: one of week/month/year/all
        limit: max number of individual trips to include in the trips list

    Returns a dict with keys:
        total_spent, trip_count, average_fare, busiest_day,
        trips, monthly_breakdown (only for year/all)
    """
    start, end = _period_bounds(period)

    # Fetch completed rides for this rider in the period
    rides_result = await db.execute(
        select(Ride)
        .where(
            Ride.rider_id == rider_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
        )
        .order_by(Ride.completed_at.desc())
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    if not all_rides:
        return {
            "total_spent": 0.0,
            "trip_count": 0,
            "average_fare": 0.0,
            "busiest_day": None,
            "trips": [],
            "monthly_breakdown": [] if period in ("year", "all") else None,
        }

    # Collect ride IDs for tip lookup
    ride_ids = [r.id for r in all_rides]

    # Look up completed tips for these rides
    tips_result = await db.execute(
        select(TipRecord).where(
            TipRecord.ride_id.in_(ride_ids),
            TipRecord.status == TipStatus.COMPLETED,
        )
    )
    tips_by_ride: dict[int, float] = {}
    for tip in tips_result.scalars().all():
        tips_by_ride[tip.ride_id] = tip.amount_cents / 100.0

    # Build per-trip detail list (limited)
    trip_details = []
    for ride in all_rides[:limit]:
        tip = tips_by_ride.get(ride.id, 0.0)
        fare = ride.actual_fare or ride.estimated_fare
        trip_details.append(
            {
                "ride_id": ride.id,
                "date": ride.completed_at.isoformat() if ride.completed_at else None,
                "pickup_address": ride.pickup_address,
                "dropoff_address": ride.dropoff_address,
                "fare": round(fare, 2),
                "tip": round(tip, 2),
                "promo_discount": round(ride.promo_discount, 2),
                "total_charged": round(fare + tip - ride.promo_discount, 2),
                "promo_code_id": ride.promo_code_id,
            }
        )

    # Aggregate totals
    total_spent = sum(
        (r.actual_fare or r.estimated_fare) + tips_by_ride.get(r.id, 0.0) - r.promo_discount
        for r in all_rides
    )
    trip_count = len(all_rides)
    average_fare = (
        sum(r.actual_fare or r.estimated_fare for r in all_rides) / trip_count
    )

    # Busiest day of week (0=Mon … 6=Sun)
    day_counts: dict[int, int] = {}
    for ride in all_rides:
        if ride.completed_at:
            dow = ride.completed_at.weekday()
            day_counts[dow] = day_counts.get(dow, 0) + 1
    busiest_dow = max(day_counts, key=lambda d: day_counts[d]) if day_counts else None
    busiest_day = _DAYS[busiest_dow] if busiest_dow is not None else None

    # Monthly breakdown (only for year/all)
    monthly_breakdown = None
    if period in ("year", "all"):
        month_totals: dict[str, dict] = {}
        for ride in all_rides:
            if not ride.completed_at:
                continue
            key = f"{ride.completed_at.year}-{ride.completed_at.month:02d}"
            if key not in month_totals:
                month_totals[key] = {"month": key, "total": 0.0, "count": 0}
            fare = (ride.actual_fare or ride.estimated_fare) + tips_by_ride.get(ride.id, 0.0) - ride.promo_discount
            month_totals[key]["total"] = round(month_totals[key]["total"] + fare, 2)
            month_totals[key]["count"] += 1
        monthly_breakdown = sorted(month_totals.values(), key=lambda x: x["month"])

    return {
        "total_spent": round(total_spent, 2),
        "trip_count": trip_count,
        "average_fare": round(average_fare, 2),
        "busiest_day": busiest_day,
        "trips": trip_details,
        "monthly_breakdown": monthly_breakdown,
    }


async def export_rider_spending_csv(
    db: AsyncSession,
    rider_id: int,
    period: str = "month",
) -> str:
    """Return CSV string of all completed rides for a rider in the period.

    Columns: date, pickup_address, dropoff_address, fare, tip,
             promo_discount, total_charged, ride_id
    """
    start, end = _period_bounds(period)

    rides_result = await db.execute(
        select(Ride)
        .where(
            Ride.rider_id == rider_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
        )
        .order_by(Ride.completed_at.desc())
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    ride_ids = [r.id for r in all_rides]
    tips_by_ride: dict[int, float] = {}
    if ride_ids:
        tips_result = await db.execute(
            select(TipRecord).where(
                TipRecord.ride_id.in_(ride_ids),
                TipRecord.status == TipStatus.COMPLETED,
            )
        )
        for tip in tips_result.scalars().all():
            tips_by_ride[tip.ride_id] = tip.amount_cents / 100.0

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["date", "pickup_address", "dropoff_address", "fare", "tip",
         "promo_discount", "total_charged", "ride_id"]
    )

    for ride in all_rides:
        fare = ride.actual_fare or ride.estimated_fare
        tip = tips_by_ride.get(ride.id, 0.0)
        total = round(fare + tip - ride.promo_discount, 2)
        writer.writerow([
            ride.completed_at.isoformat() if ride.completed_at else "",
            ride.pickup_address,
            ride.dropoff_address,
            round(fare, 2),
            round(tip, 2),
            round(ride.promo_discount, 2),
            total,
            ride.id,
        ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Driver tax summary
# ---------------------------------------------------------------------------


async def get_driver_tax_summary(
    db: AsyncSession,
    driver_id: int,
    year: int,
) -> dict[str, Any]:
    """Return annual tax summary for a driver.

    NOTE: This is an estimate provided for convenience only. It does not
    constitute tax advice. Drivers should consult a qualified tax professional.

    Returns a dict with:
        year, gross_earnings, tips_received, bonuses_received,
        total_income, platform_fees_paid, rides_completed,
        miles_driven_estimate, quarterly_breakdown, disclaimer
    """
    start, end = _year_bounds(year)

    # Fetch all completed rides driven by this driver in the year
    rides_result = await db.execute(
        select(Ride)
        .where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
        )
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    ride_ids = [r.id for r in all_rides]

    # Tips received by this driver
    tips_by_ride: dict[int, float] = {}
    if ride_ids:
        tips_result = await db.execute(
            select(TipRecord).where(
                TipRecord.ride_id.in_(ride_ids),
                TipRecord.driver_id == driver_id,
                TipRecord.status == TipStatus.COMPLETED,
            )
        )
        for tip in tips_result.scalars().all():
            tips_by_ride[tip.ride_id] = tip.amount_cents / 100.0

    # Platform fees via payments table (driver_payout vs amount tells us fee)
    platform_fees_by_ride: dict[int, float] = {}
    if ride_ids:
        payments_result = await db.execute(
            select(Payment).where(
                Payment.ride_id.in_(ride_ids),
                Payment.status == PaymentStatus.COMPLETED,
            )
        )
        for payment in payments_result.scalars().all():
            platform_fees_by_ride[payment.ride_id] = payment.platform_fee

    # Incentive bonuses paid out in this year
    bonuses_result = await db.execute(
        select(DriverIncentiveProgress).where(
            DriverIncentiveProgress.driver_id == driver_id,
            DriverIncentiveProgress.status == ProgressStatus.PAID.value,
            DriverIncentiveProgress.paid_at >= start,
            DriverIncentiveProgress.paid_at <= end,
        )
    )
    bonus_records = list(bonuses_result.scalars().all())
    total_bonuses = sum(b.bonus_earned for b in bonus_records)

    # Aggregate totals
    gross_earnings = sum(r.actual_fare or r.estimated_fare for r in all_rides)
    tips_received = sum(tips_by_ride.values())
    platform_fees_paid = sum(platform_fees_by_ride.values())
    rides_completed = len(all_rides)

    # Miles estimate (distance_km * 0.621371 if available)
    distances = [r.distance_km for r in all_rides if r.distance_km is not None]
    miles_driven_estimate = (
        round(sum(distances) * 0.621371, 1) if distances else None
    )

    total_income = gross_earnings + tips_received + total_bonuses

    # Quarterly breakdown
    quarters: dict[str, dict] = {}
    for ride in all_rides:
        if not ride.completed_at:
            continue
        q = _quarter(ride.completed_at.month)
        if q not in quarters:
            quarters[q] = {"quarter": q, "gross": 0.0, "tips": 0.0, "bonuses": 0.0, "total": 0.0}
        fare = ride.actual_fare or ride.estimated_fare
        quarters[q]["gross"] = round(quarters[q]["gross"] + fare, 2)
        tip = tips_by_ride.get(ride.id, 0.0)
        quarters[q]["tips"] = round(quarters[q]["tips"] + tip, 2)

    # Distribute bonuses into Q by paid_at date
    for bonus in bonus_records:
        if bonus.paid_at:
            q = _quarter(bonus.paid_at.month)
            if q not in quarters:
                quarters[q] = {"quarter": q, "gross": 0.0, "tips": 0.0, "bonuses": 0.0, "total": 0.0}
            quarters[q]["bonuses"] = round(quarters[q]["bonuses"] + bonus.bonus_earned, 2)

    for q_data in quarters.values():
        q_data["total"] = round(q_data["gross"] + q_data["tips"] + q_data["bonuses"], 2)

    quarterly_breakdown = sorted(quarters.values(), key=lambda x: x["quarter"])

    return {
        "year": year,
        "gross_earnings": round(gross_earnings, 2),
        "tips_received": round(tips_received, 2),
        "bonuses_received": round(total_bonuses, 2),
        "total_income": round(total_income, 2),
        "platform_fees_paid": round(platform_fees_paid, 2),
        "rides_completed": rides_completed,
        "miles_driven_estimate": miles_driven_estimate,
        "quarterly_breakdown": quarterly_breakdown,
        "disclaimer": (
            "This summary is an estimate provided for your convenience only. "
            "It does not constitute tax advice. Please consult a qualified tax "
            "professional for guidance on your specific tax obligations."
        ),
    }


async def export_driver_tax_csv(
    db: AsyncSession,
    driver_id: int,
    year: int,
) -> str:
    """Return CSV string of all completed rides driven in the given year.

    Columns: date, ride_id, fare_earned, tip, bonus, total, ride_duration_minutes
    """
    start, end = _year_bounds(year)

    rides_result = await db.execute(
        select(Ride)
        .where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
        )
        .order_by(Ride.completed_at.asc())
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    ride_ids = [r.id for r in all_rides]
    tips_by_ride: dict[int, float] = {}
    if ride_ids:
        tips_result = await db.execute(
            select(TipRecord).where(
                TipRecord.ride_id.in_(ride_ids),
                TipRecord.driver_id == driver_id,
                TipRecord.status == TipStatus.COMPLETED,
            )
        )
        for tip in tips_result.scalars().all():
            tips_by_ride[tip.ride_id] = tip.amount_cents / 100.0

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["date", "ride_id", "fare_earned", "tip", "bonus", "total", "ride_duration_minutes"]
    )

    for ride in all_rides:
        fare = ride.actual_fare or ride.estimated_fare
        tip = tips_by_ride.get(ride.id, 0.0)
        # bonus column: 0 here (bonuses are per incentive program, not per ride)
        bonus = 0.0
        total = round(fare + tip + bonus, 2)
        duration = round(ride.duration_min, 1) if ride.duration_min is not None else ""
        writer.writerow([
            ride.completed_at.isoformat() if ride.completed_at else "",
            ride.id,
            round(fare, 2),
            round(tip, 2),
            bonus,
            total,
            duration,
        ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Tip analytics
# ---------------------------------------------------------------------------


async def get_driver_tip_summary(
    db: AsyncSession,
    driver_id: int,
    period: str,
) -> dict[str, Any]:
    """Return tip earnings summary for a driver over the given period.

    period must be one of: week, month, year, all.

    Returns a dict matching TipSummaryResponse schema fields.
    """
    start, end = _period_bounds(period)

    result = await db.execute(
        select(TipRecord).where(
            TipRecord.driver_id == driver_id,
            TipRecord.created_at >= start,
            TipRecord.created_at <= end,
        )
    )
    tips = result.scalars().all()

    status_counts: dict[str, int] = {"completed": 0, "pending": 0, "failed": 0, "refunded": 0}
    total_cents = 0
    for tip in tips:
        total_cents += tip.amount_cents
        status_key = tip.status.value if hasattr(tip.status, "value") else str(tip.status)
        if status_key in status_counts:
            status_counts[status_key] += 1

    tip_count = len(tips)
    avg_tip_cents = (total_cents // tip_count) if tip_count else 0

    return {
        "period": period,
        "total_cents": total_cents,
        "total_dollars": round(total_cents / 100, 2),
        "tip_count": tip_count,
        "avg_tip_cents": avg_tip_cents,
        "avg_tip_dollars": round(avg_tip_cents / 100, 2),
        "status_breakdown": status_counts,
    }


async def get_admin_tip_stats(
    db: AsyncSession,
    period: str,
) -> dict[str, Any]:
    """Return platform-wide tip analytics for the given period.

    period must be one of: week, month, year, all.

    Returns a dict matching AdminTipStatsResponse schema fields.
    """
    start, end = _period_bounds(period)

    result = await db.execute(
        select(TipRecord).where(
            TipRecord.created_at >= start,
            TipRecord.created_at <= end,
        )
    )
    tips = result.scalars().all()

    total_cents = sum(t.amount_cents for t in tips)
    tip_count = len(tips)
    avg_tip_cents = (total_cents // tip_count) if tip_count else 0

    unique_drivers = len({t.driver_id for t in tips})
    unique_riders = len({t.rider_id for t in tips})

    # Build per-driver totals for top-10 list
    driver_totals: dict[int, dict[str, int]] = {}
    for tip in tips:
        entry = driver_totals.setdefault(tip.driver_id, {"tip_count": 0, "total_cents": 0})
        entry["tip_count"] += 1
        entry["total_cents"] += tip.amount_cents

    top_drivers = sorted(
        driver_totals.items(),
        key=lambda x: x[1]["total_cents"],
        reverse=True,
    )[:10]

    return {
        "period": period,
        "total_cents": total_cents,
        "total_dollars": round(total_cents / 100, 2),
        "tip_count": tip_count,
        "avg_tip_cents": avg_tip_cents,
        "avg_tip_dollars": round(avg_tip_cents / 100, 2),
        "unique_drivers_tipped": unique_drivers,
        "unique_riders_who_tipped": unique_riders,
        "top_tipped_drivers": [
            {
                "driver_id": driver_id,
                "tip_count": stats["tip_count"],
                "total_cents": stats["total_cents"],
                "total_dollars": round(stats["total_cents"] / 100, 2),
            }
            for driver_id, stats in top_drivers
        ],
    }

    return output.getvalue()
