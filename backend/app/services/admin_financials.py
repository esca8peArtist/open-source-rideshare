"""Admin financial reconciliation service.

Provides platform-level financial aggregations for admins:
  - Summary of gross/net revenue, payouts, refunds, and key metrics
  - Per-ride CSV export for reconciliation
  - Driver payout status listing

All functions are read-only; no data is mutated here.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.payout import DriverPayout, PayoutStatus
from app.models.promo import PromoRedemption
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.models.user import User


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _date_to_utc_start(d: date) -> datetime:
    """Convert a date to a UTC-aware datetime at midnight."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_to_utc_end(d: date) -> datetime:
    """Convert a date to a UTC-aware datetime at end of day (23:59:59)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


async def get_financial_summary(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Return a platform-level financial reconciliation summary for the period.

    Args:
        db: async database session
        start_date: inclusive start date
        end_date: inclusive end date

    Returns a dict with:
        period, gross_platform_revenue, total_ride_fares, total_tips_collected,
        total_promo_discounts_applied, total_refunds_issued, total_driver_payouts,
        net_platform_revenue, ride_count, active_drivers, active_riders,
        average_fare, daily_breakdown
    """
    start = _date_to_utc_start(start_date)
    end = _date_to_utc_end(end_date)

    # Completed rides in the period
    rides_result = await db.execute(
        select(Ride).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
        )
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    if not all_rides:
        return {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "gross_platform_revenue": 0.0,
            "total_ride_fares": 0.0,
            "total_tips_collected": 0.0,
            "total_promo_discounts_applied": 0.0,
            "total_refunds_issued": 0.0,
            "total_driver_payouts": 0.0,
            "net_platform_revenue": 0.0,
            "ride_count": 0,
            "active_drivers": 0,
            "active_riders": 0,
            "average_fare": 0.0,
            "daily_breakdown": [],
        }

    ride_ids = [r.id for r in all_rides]

    # Payments for these rides
    payments_result = await db.execute(
        select(Payment).where(
            Payment.ride_id.in_(ride_ids),
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    payments: list[Payment] = list(payments_result.scalars().all())
    platform_fee_by_ride: dict[int, float] = {p.ride_id: p.platform_fee for p in payments}
    refund_by_ride: dict[int, float] = {}
    for p in payments:
        if p.status == PaymentStatus.REFUNDED:
            refund_by_ride[p.ride_id] = p.amount

    # Refunded payments (separate query — status=REFUNDED)
    refunds_result = await db.execute(
        select(Payment).where(
            Payment.ride_id.in_(ride_ids),
            Payment.status == PaymentStatus.REFUNDED,
        )
    )
    refund_payments: list[Payment] = list(refunds_result.scalars().all())
    total_refunds_issued = sum(p.amount for p in refund_payments)

    # Tips for these rides
    tips_result = await db.execute(
        select(TipRecord).where(
            TipRecord.ride_id.in_(ride_ids),
            TipRecord.status == TipStatus.COMPLETED,
        )
    )
    tips: list[TipRecord] = list(tips_result.scalars().all())
    tips_by_ride: dict[int, float] = {t.ride_id: t.amount_cents / 100.0 for t in tips}

    # Promo redemptions for these rides
    promos_result = await db.execute(
        select(PromoRedemption).where(
            PromoRedemption.ride_id.in_(ride_ids),
        )
    )
    promos: list[PromoRedemption] = list(promos_result.scalars().all())
    promo_by_ride: dict[int, float] = {p.ride_id: p.discount_amount for p in promos}

    # Driver payouts settled in this period
    payouts_result = await db.execute(
        select(DriverPayout).where(
            DriverPayout.status == PayoutStatus.COMPLETED,
            DriverPayout.completed_at >= start,
            DriverPayout.completed_at <= end,
        )
    )
    payout_records: list[DriverPayout] = list(payouts_result.scalars().all())
    total_driver_payouts = sum(dp.total_amount for dp in payout_records)

    # Aggregate ride-level figures
    total_ride_fares = sum(r.actual_fare or r.estimated_fare for r in all_rides)
    total_tips_collected = sum(tips_by_ride.values())
    total_promo_discounts_applied = sum(promo_by_ride.values())
    gross_platform_revenue = sum(platform_fee_by_ride.values())
    net_platform_revenue = round(gross_platform_revenue - total_refunds_issued, 2)

    ride_count = len(all_rides)
    active_drivers = len({r.driver_id for r in all_rides if r.driver_id is not None})
    active_riders = len({r.rider_id for r in all_rides})
    average_fare = round(total_ride_fares / ride_count, 2) if ride_count else 0.0

    # Daily breakdown
    daily: dict[str, dict[str, Any]] = {}
    for ride in all_rides:
        if not ride.completed_at:
            continue
        day_key = ride.completed_at.date().isoformat()
        if day_key not in daily:
            daily[day_key] = {
                "date": day_key,
                "ride_count": 0,
                "gross_revenue": 0.0,
                "net_revenue": 0.0,
            }
        fare = ride.actual_fare or ride.estimated_fare
        fee = platform_fee_by_ride.get(ride.id, 0.0)
        daily[day_key]["ride_count"] += 1
        daily[day_key]["gross_revenue"] = round(daily[day_key]["gross_revenue"] + fee, 2)
        # net_revenue: gross minus any refund on that ride's payment
        daily[day_key]["net_revenue"] = round(daily[day_key]["net_revenue"] + fee, 2)

    daily_breakdown = sorted(daily.values(), key=lambda d: d["date"])

    return {
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "gross_platform_revenue": round(gross_platform_revenue, 2),
        "total_ride_fares": round(total_ride_fares, 2),
        "total_tips_collected": round(total_tips_collected, 2),
        "total_promo_discounts_applied": round(total_promo_discounts_applied, 2),
        "total_refunds_issued": round(total_refunds_issued, 2),
        "total_driver_payouts": round(total_driver_payouts, 2),
        "net_platform_revenue": net_platform_revenue,
        "ride_count": ride_count,
        "active_drivers": active_drivers,
        "active_riders": active_riders,
        "average_fare": average_fare,
        "daily_breakdown": daily_breakdown,
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


async def export_reconciliation_csv(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> str:
    """Return a CSV string of per-ride financial data for the period.

    Columns: date, ride_id, rider_id, driver_id, fare, tip, promo_discount,
             platform_fee, driver_payout, refund_amount, net_platform
    """
    start = _date_to_utc_start(start_date)
    end = _date_to_utc_end(end_date)

    rides_result = await db.execute(
        select(Ride).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
        ).order_by(Ride.completed_at.asc())
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    ride_ids = [r.id for r in all_rides]

    # Payments
    payments_by_ride: dict[int, Payment] = {}
    refund_amounts: dict[int, float] = {}
    if ride_ids:
        payments_result = await db.execute(
            select(Payment).where(Payment.ride_id.in_(ride_ids))
        )
        for p in payments_result.scalars().all():
            if p.status == PaymentStatus.COMPLETED:
                payments_by_ride[p.ride_id] = p
            elif p.status == PaymentStatus.REFUNDED:
                refund_amounts[p.ride_id] = p.amount

    # Tips
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

    # Promo redemptions
    promo_by_ride: dict[int, float] = {}
    if ride_ids:
        promos_result = await db.execute(
            select(PromoRedemption).where(PromoRedemption.ride_id.in_(ride_ids))
        )
        for promo in promos_result.scalars().all():
            promo_by_ride[promo.ride_id] = promo.discount_amount

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "date", "ride_id", "rider_id", "driver_id", "fare", "tip",
        "promo_discount", "platform_fee", "driver_payout",
        "refund_amount", "net_platform",
    ])

    for ride in all_rides:
        fare = ride.actual_fare or ride.estimated_fare
        tip = tips_by_ride.get(ride.id, 0.0)
        promo_discount = promo_by_ride.get(ride.id, ride.promo_discount)
        payment = payments_by_ride.get(ride.id)
        platform_fee = payment.platform_fee if payment else 0.0
        driver_payout_amt = payment.driver_payout if payment else 0.0
        refund_amount = refund_amounts.get(ride.id, 0.0)
        net_platform = round(platform_fee - refund_amount, 2)

        writer.writerow([
            ride.completed_at.isoformat() if ride.completed_at else "",
            ride.id,
            ride.rider_id,
            ride.driver_id if ride.driver_id is not None else "",
            round(fare, 2),
            round(tip, 2),
            round(promo_discount, 2),
            round(platform_fee, 2),
            round(driver_payout_amt, 2),
            round(refund_amount, 2),
            net_platform,
        ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Payout status
# ---------------------------------------------------------------------------


async def get_payout_status(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return driver payout records for the period, optionally filtered by status.

    Args:
        db: async database session
        start_date: inclusive start date (filters by payout created_at)
        end_date: inclusive end date
        status: optional filter — one of pending/processing/completed/failed

    Each record includes: driver_id, driver_name, payout_amount, payout_date,
    status, ride_count_in_period
    """
    start = _date_to_utc_start(start_date)
    end = _date_to_utc_end(end_date)

    query = select(DriverPayout).where(
        DriverPayout.created_at >= start,
        DriverPayout.created_at <= end,
    )

    if status is not None:
        # Validate and convert to enum
        try:
            status_enum = PayoutStatus(status)
        except ValueError:
            # Return empty list for unknown status rather than raise
            return []
        query = query.where(DriverPayout.status == status_enum)

    payouts_result = await db.execute(query.order_by(DriverPayout.created_at.desc()))
    payouts: list[DriverPayout] = list(payouts_result.scalars().all())

    if not payouts:
        return []

    # Fetch driver names
    driver_ids = list({p.driver_id for p in payouts})
    users_result = await db.execute(
        select(User).where(User.id.in_(driver_ids))
    )
    users_by_id: dict[int, User] = {u.id: u for u in users_result.scalars().all()}

    results = []
    for payout in payouts:
        driver = users_by_id.get(payout.driver_id)
        payout_date = (
            payout.completed_at or payout.processed_at or payout.created_at
        )
        results.append({
            "driver_id": payout.driver_id,
            "driver_name": driver.name if driver else "Unknown",
            "payout_amount": round(payout.total_amount, 2),
            "payout_date": payout_date.isoformat() if payout_date else None,
            "status": payout.status.value,
            "ride_count_in_period": payout.trip_count,
        })

    return results
