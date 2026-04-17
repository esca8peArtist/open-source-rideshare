"""Driver earnings comparison service.

Compares a driver's actual OpenRide payouts to estimated competitor (Uber/Lyft)
payouts for the same set of completed rides, using published platform rate cards.

Public API:
  get_earnings_comparison(db, driver_id, start_date, end_date)
      → EarningsComparisonResponse

Rate card methodology:
  Competitor earnings are modelled as:
      driver_payout = (base_fare + per_min * duration + per_mile * distance)
                      * driver_take_rate

  Rate card source: 2025 US national average surveys (rideshare driver community
  aggregates, RideGuru rate database).  Rates vary by city and surge conditions;
  these national averages are documented for transparency, not precision.

  Uber XL / Lyft XL surcharges and other vehicle categories are not modelled
  separately — all rides use the standard/UberX/Lyft Standard rate card.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.schemas.driver_earnings_comparison import (
    EarningsComparisonResponse,
    PlatformRateCard,
)

# ---------------------------------------------------------------------------
# Published rate cards (2025 US national averages)
# Source: RideGuru national average survey, driver community aggregates
# ---------------------------------------------------------------------------

_UBER_RATE_CARD = PlatformRateCard(
    platform_name="Uber (UberX)",
    base_fare_usd=1.38,
    per_minute_usd=0.20,
    per_mile_usd=0.84,
    driver_take_rate=0.75,
    source_note=(
        "2025 US national average for UberX; driver take rate ~75% after Uber's "
        "~25% service fee. Source: RideGuru national average rate survey, "
        "rideshare driver community aggregates. Rates vary by city and surge."
    ),
)

_LYFT_RATE_CARD = PlatformRateCard(
    platform_name="Lyft (Standard)",
    base_fare_usd=1.25,
    per_minute_usd=0.22,
    per_mile_usd=0.83,
    driver_take_rate=0.75,
    source_note=(
        "2025 US national average for Lyft Standard; driver take rate ~75% after "
        "Lyft's ~25% service fee. Source: RideGuru national average rate survey, "
        "rideshare driver community aggregates. Rates vary by city and surge."
    ),
)

_KM_TO_MILES = 0.621371

_METHODOLOGY_NOTE = (
    "Competitor earnings are estimates based on published 2025 US national average "
    "rate cards for UberX and Lyft Standard. Actual competitor rates vary significantly "
    "by city, time of day, and surge conditions. Tips are included in OpenRide totals "
    "but are not modelled in competitor estimates. This comparison is for informational "
    "purposes only."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _start_of_month(d: date) -> date:
    return d.replace(day=1)


def _to_utc_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _to_utc_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def _estimate_driver_payout(
    distance_km: float,
    duration_min: float,
    card: PlatformRateCard,
) -> float:
    """Estimate what a driver would receive for a ride on a competitor platform."""
    distance_miles = distance_km * _KM_TO_MILES
    gross = (
        card.base_fare_usd
        + card.per_minute_usd * duration_min
        + card.per_mile_usd * distance_miles
    )
    return round(gross * card.driver_take_rate, 4)


def _pct_delta(openride: float, competitor: float) -> float:
    """Return (openride / competitor - 1) * 100, rounded to 2 dp.

    Returns 0.0 when competitor estimate is zero to avoid division by zero.
    """
    if competitor == 0.0:
        return 0.0
    return round((openride / competitor - 1.0) * 100.0, 2)


# ---------------------------------------------------------------------------
# Database fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_completed_rides(
    db: AsyncSession,
    driver_id: int,
    start: date,
    end: date,
) -> list[Ride]:
    """Return completed rides for the driver within the date range."""
    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= _to_utc_start(start),
            Ride.completed_at <= _to_utc_end(end),
        )
    )
    return list(result.scalars().all())


async def _fetch_payouts(
    db: AsyncSession,
    ride_ids: list[int],
) -> dict[int, float]:
    """Return {ride_id: driver_payout} for a set of ride IDs.

    Uses the RIDE_FARE payment type for each ride.
    """
    if not ride_ids:
        return {}
    result = await db.execute(
        select(Payment.ride_id, Payment.driver_payout).where(
            Payment.ride_id.in_(ride_ids),
            Payment.payment_type == PaymentType.RIDE_FARE,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    return {row.ride_id: float(row.driver_payout) for row in result}


async def _fetch_tips(
    db: AsyncSession,
    driver_id: int,
    ride_ids: list[int],
) -> dict[int, float]:
    """Return {ride_id: tip_amount} for completed tips on the driver's rides."""
    if not ride_ids:
        return {}
    result = await db.execute(
        select(TipRecord.ride_id, TipRecord.amount_cents).where(
            TipRecord.driver_id == driver_id,
            TipRecord.ride_id.in_(ride_ids),
            TipRecord.status == TipStatus.COMPLETED,
        )
    )
    tips: dict[int, float] = {}
    for row in result:
        # amount_cents is stored as integer (e.g. 500 = $5.00)
        tips[row.ride_id] = tips.get(row.ride_id, 0.0) + row.amount_cents / 100.0
    return tips


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


async def get_earnings_comparison(
    db: AsyncSession,
    driver_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> EarningsComparisonResponse:
    """Compare the driver's actual OpenRide payouts to estimated competitor payouts.

    Args:
        db:          Database session.
        driver_id:   Authenticated driver's user ID.
        start_date:  Inclusive start; defaults to first day of current month.
        end_date:    Inclusive end; defaults to today.

    Returns:
        EarningsComparisonResponse with actuals, estimates, and deltas.
    """
    today = datetime.now(tz=timezone.utc).date()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = _start_of_month(today)

    # Clamp reversed ranges silently
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Fetch all completed rides in the window
    all_rides = await _fetch_completed_rides(db, driver_id, start_date, end_date)

    if not all_rides:
        return EarningsComparisonResponse(
            period_start=start_date,
            period_end=end_date,
            rides_analyzed=0,
            rides_excluded=0,
            total_distance_km=0.0,
            total_distance_miles=0.0,
            total_duration_min=0.0,
            openride_total_payout=0.0,
            openride_total_tips=0.0,
            openride_avg_payout_per_ride=0.0,
            openride_avg_payout_per_mile=0.0,
            openride_avg_payout_per_hour=0.0,
            uber_estimated_total_payout=0.0,
            lyft_estimated_total_payout=0.0,
            openride_vs_uber_delta=0.0,
            openride_vs_lyft_delta=0.0,
            openride_vs_uber_pct=0.0,
            openride_vs_lyft_pct=0.0,
            uber_rate_card=_UBER_RATE_CARD,
            lyft_rate_card=_LYFT_RATE_CARD,
            methodology_note=_METHODOLOGY_NOTE,
        )

    all_ride_ids = [r.id for r in all_rides]
    payouts_by_ride = await _fetch_payouts(db, all_ride_ids)
    tips_by_ride = await _fetch_tips(db, driver_id, all_ride_ids)

    # Split rides into analyzable (have distance + duration) vs. excluded
    analyzable = [
        r
        for r in all_rides
        if r.distance_km is not None and r.duration_min is not None
    ]
    excluded_count = len(all_rides) - len(analyzable)

    # Aggregate OpenRide actuals from Payment records
    # Fall back to actual_fare / estimated_fare if no payment record (e.g. cash)
    total_openride_payout = 0.0
    total_tips = 0.0
    total_distance_km = 0.0
    total_duration_min = 0.0
    total_uber_est = 0.0
    total_lyft_est = 0.0

    for ride in analyzable:
        dist_km: float = ride.distance_km  # type: ignore[assignment]
        dur_min: float = ride.duration_min  # type: ignore[assignment]

        # OpenRide payout: prefer Payment record, fall back to fare fields
        payout = payouts_by_ride.get(ride.id)
        if payout is None:
            payout = float(ride.actual_fare or ride.estimated_fare or 0.0)
        tip = tips_by_ride.get(ride.id, 0.0)

        total_openride_payout += payout + tip
        total_tips += tip
        total_distance_km += dist_km
        total_duration_min += dur_min

        total_uber_est += _estimate_driver_payout(dist_km, dur_min, _UBER_RATE_CARD)
        total_lyft_est += _estimate_driver_payout(dist_km, dur_min, _LYFT_RATE_CARD)

    n = len(analyzable)
    total_openride_payout = round(total_openride_payout, 2)
    total_uber_est = round(total_uber_est, 2)
    total_lyft_est = round(total_lyft_est, 2)
    total_distance_miles = round(total_distance_km * _KM_TO_MILES, 2)

    avg_per_ride = round(total_openride_payout / n, 2) if n else 0.0
    avg_per_mile = (
        round(total_openride_payout / total_distance_miles, 2)
        if total_distance_miles > 0
        else 0.0
    )
    total_hours = total_duration_min / 60.0
    avg_per_hour = (
        round(total_openride_payout / total_hours, 2) if total_hours > 0 else 0.0
    )

    uber_delta = round(total_openride_payout - total_uber_est, 2)
    lyft_delta = round(total_openride_payout - total_lyft_est, 2)

    return EarningsComparisonResponse(
        period_start=start_date,
        period_end=end_date,
        rides_analyzed=n,
        rides_excluded=excluded_count,
        total_distance_km=round(total_distance_km, 2),
        total_distance_miles=total_distance_miles,
        total_duration_min=round(total_duration_min, 2),
        openride_total_payout=total_openride_payout,
        openride_total_tips=round(total_tips, 2),
        openride_avg_payout_per_ride=avg_per_ride,
        openride_avg_payout_per_mile=avg_per_mile,
        openride_avg_payout_per_hour=avg_per_hour,
        uber_estimated_total_payout=total_uber_est,
        lyft_estimated_total_payout=total_lyft_est,
        openride_vs_uber_delta=uber_delta,
        openride_vs_lyft_delta=lyft_delta,
        openride_vs_uber_pct=_pct_delta(total_openride_payout, total_uber_est),
        openride_vs_lyft_pct=_pct_delta(total_openride_payout, total_lyft_est),
        uber_rate_card=_UBER_RATE_CARD,
        lyft_rate_card=_LYFT_RATE_CARD,
        methodology_note=_METHODOLOGY_NOTE,
    )
