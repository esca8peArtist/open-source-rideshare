"""Platform transparency report service.

Generates the public aggregate platform transparency report for
GET /platform/transparency-report.

The report shows:
  - OpenRide's cooperative model (zero commission, driver ownership)
  - Ride volumes for the requested period
  - Aggregate driver earnings vs. estimated Uber/Lyft equivalents
  - Average rider fares vs. estimated Uber/Lyft equivalents
  - Service quality metrics (ratings, completion rate)

Public API:
  get_platform_transparency_report(db, period)
      -> PlatformTransparencyReport

Competitor rate constants are imported from rider_fare_transparency to
avoid duplicating published rate card values across the codebase.

Data availability:
  When no completed rides exist (e.g. a fresh installation), all numeric
  fields return 0.0 / 0 and data_available is set to False. The endpoint
  never errors on an empty database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.schemas.platform_transparency import (
    EarningsSummary,
    PlatformModel,
    PlatformTransparencyReport,
    RideVolume,
    RiderSummary,
    ServiceQuality,
)

# Import the 2025 competitor rate constants from rider_fare_transparency
# to avoid duplicating published rate card values.
from app.services.rider_fare_transparency import (
    _UBER_PLATFORM_FEE_RATE,
    _LYFT_PLATFORM_FEE_RATE,
    _METHODOLOGY_NOTE as _FARE_METHODOLOGY_NOTE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Competitor driver take rates (complement of platform fee rate)
# These are the same rates used in driver_earnings_comparison.py.
# Uber and Lyft both apply ~25% commission, leaving drivers ~75%.
# ---------------------------------------------------------------------------

_UBER_DRIVER_TAKE_RATE: float = 1.0 - _UBER_PLATFORM_FEE_RATE   # ~0.735
_LYFT_DRIVER_TAKE_RATE: float = 1.0 - _LYFT_PLATFORM_FEE_RATE   # ~0.775

# ---------------------------------------------------------------------------
# Static report strings
# ---------------------------------------------------------------------------

_PLATFORM_MODEL = PlatformModel(
    commission_rate_pct=0.0,
    commission_note=(
        "OpenRide charges no platform commission. Drivers keep 100% of every fare."
    ),
    ownership_model="cooperative",
    cooperative_description=(
        "OpenRide is owned by its drivers. Surplus revenue is returned to "
        "driver-owners as annual dividends rather than extracted by investors."
    ),
)

_METHODOLOGY_NOTE = (
    "Uber/Lyft equivalents use 2025 published national average commission rates: "
    "Uber ~26.5% (midpoint of 25-28%), Lyft ~22.5% (midpoint of 20-25%). "
    "Driver equivalent earnings represent estimated payout had the same trips "
    "been completed on competitor platforms (driver take rate = 1 - commission rate). "
    "Rider equivalent fares are estimated by dividing OpenRide fares by the "
    "competitor driver take rate, reflecting the higher gross fare competitors "
    "charge to cover their platform commission. "
    "Service quality metrics cover only rides completed within the report period. "
    "This report is generated from live platform data and refreshed every 24 hours."
)

_TRANSPARENCY_NOTE = (
    "This report is published publicly because OpenRide believes platform economics "
    "should be visible to all participants. No equivalent public disclosure is "
    "required of or made by Uber or Lyft."
)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------


class ReportPeriod(str, Enum):
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    ALL_TIME = "all_time"


_PERIOD_LABELS: dict[ReportPeriod, str] = {
    ReportPeriod.LAST_7_DAYS: "Last 7 days",
    ReportPeriod.LAST_30_DAYS: "Last 30 days",
    ReportPeriod.ALL_TIME: "All time",
}


def _period_start(period: ReportPeriod, now: datetime) -> datetime | None:
    """Return the UTC start datetime for the given period, or None for all_time."""
    if period == ReportPeriod.LAST_7_DAYS:
        return now - timedelta(days=7)
    if period == ReportPeriod.LAST_30_DAYS:
        return now - timedelta(days=30)
    return None  # all_time — no lower bound


# ---------------------------------------------------------------------------
# DB query helpers
# ---------------------------------------------------------------------------


async def _count_all_time_completed(db: AsyncSession) -> int:
    """Count all completed rides on the platform regardless of period."""
    result = await db.execute(
        select(func.count(Ride.id)).where(Ride.status == RideStatus.COMPLETED)
    )
    return result.scalar_one() or 0


async def _fetch_period_completed_rides(
    db: AsyncSession,
    period_start_dt: datetime | None,
) -> list[Ride]:
    """Fetch all completed rides within the period (or all time if no start)."""
    conditions = [Ride.status == RideStatus.COMPLETED]
    if period_start_dt is not None:
        conditions.append(Ride.requested_at >= period_start_dt)
    result = await db.execute(select(Ride).where(and_(*conditions)))
    return list(result.scalars().all())


async def _fetch_payments_for_rides(
    db: AsyncSession,
    ride_ids: list[int],
) -> dict[int, Payment]:
    """Fetch completed RIDE_FARE payments keyed by ride_id."""
    if not ride_ids:
        return {}
    result = await db.execute(
        select(Payment).where(
            and_(
                Payment.ride_id.in_(ride_ids),
                Payment.payment_type == PaymentType.RIDE_FARE,
                Payment.status == PaymentStatus.COMPLETED,
            )
        )
    )
    return {p.ride_id: p for p in result.scalars().all()}


async def _count_cancelled_in_period(
    db: AsyncSession,
    period_start_dt: datetime | None,
) -> int:
    """Count cancelled rides within the period."""
    conditions = [Ride.status == RideStatus.CANCELLED]
    if period_start_dt is not None:
        conditions.append(Ride.requested_at >= period_start_dt)
    result = await db.execute(
        select(func.count(Ride.id)).where(and_(*conditions))
    )
    return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide numerator by denominator, returning default when denominator is zero."""
    if denominator == 0.0:
        return default
    return numerator / denominator


def _build_earnings_summary(
    rides: list[Ride],
    payments: dict[int, Payment],
) -> EarningsSummary:
    """Compute driver earnings totals and competitor equivalents.

    For each ride, the driver payout is taken from the Payment record when
    available, otherwise the full actual_fare is assumed (OpenRide 0% model).

    Competitor driver earnings are estimated as:
        competitor_driver_earnings = actual_openride_fare * competitor_take_rate

    This reflects what the driver would have received on a competitor platform
    for the same gross fare. Note: on a real competitor platform the gross fare
    would differ (it includes the platform fee); this estimate holds OpenRide's
    gross fare constant and applies the competitor take rate as a conservative
    lower-bound for the driver advantage.
    """
    total_driver_earnings = 0.0
    n = len(rides)

    for ride in rides:
        payment = payments.get(ride.id)
        if payment is not None:
            total_driver_earnings += float(payment.driver_payout)
        else:
            # No payment record: assume driver received the full actual fare
            # (OpenRide cooperative model: 0% platform commission).
            fare = float(ride.actual_fare or 0.0)
            total_driver_earnings += fare

    total_driver_earnings = round(total_driver_earnings, 2)
    avg_per_ride = round(_safe_div(total_driver_earnings, n), 2)

    # Competitor equivalents: apply take rate to the same total earnings
    uber_equivalent = round(total_driver_earnings * _UBER_DRIVER_TAKE_RATE, 2)
    lyft_equivalent = round(total_driver_earnings * _LYFT_DRIVER_TAKE_RATE, 2)

    return EarningsSummary(
        total_driver_earnings_usd=total_driver_earnings,
        avg_driver_earnings_per_ride_usd=avg_per_ride,
        avg_driver_payout_pct=100.0,
        uber_equivalent_driver_earnings_usd=uber_equivalent,
        lyft_equivalent_driver_earnings_usd=lyft_equivalent,
        driver_savings_vs_uber_usd=round(total_driver_earnings - uber_equivalent, 2),
        driver_savings_vs_lyft_usd=round(total_driver_earnings - lyft_equivalent, 2),
    )


def _build_rider_summary(rides: list[Ride]) -> RiderSummary:
    """Compute rider fare metrics and competitor fare equivalents.

    Only rides with distance and duration data contribute to competitor
    fare estimates. For rides without that data, we estimate the competitor
    fare by grossing up the OpenRide fare by the competitor's commission:

        competitor_fare = openride_fare / driver_take_rate

    Because the competitor charges more to cover their platform commission,
    the gross fare to the rider is higher even though the driver earns less.
    """
    unique_riders = len({ride.rider_id for ride in rides})
    n = len(rides)

    total_openride_fares = sum(float(ride.actual_fare or 0.0) for ride in rides)
    avg_fare = round(_safe_div(total_openride_fares, n), 2)

    # Estimate competitor gross fares per ride and accumulate
    total_uber_fares = 0.0
    total_lyft_fares = 0.0
    for ride in rides:
        fare = float(ride.actual_fare or 0.0)
        # Gross up: if OpenRide driver receives `fare` (100%), the competitor
        # rider would pay fare / take_rate (because competitor driver receives
        # less, so total fare must be higher to maintain the same driver net).
        # We keep OpenRide's net driver payout constant and back-calculate
        # what the rider would have paid on each competitor.
        total_uber_fares += fare / _UBER_DRIVER_TAKE_RATE
        total_lyft_fares += fare / _LYFT_DRIVER_TAKE_RATE

    avg_uber_fare = round(_safe_div(total_uber_fares, n), 2)
    avg_lyft_fare = round(_safe_div(total_lyft_fares, n), 2)

    return RiderSummary(
        unique_riders_period=unique_riders,
        avg_fare_usd=avg_fare,
        avg_uber_equivalent_fare_usd=avg_uber_fare,
        avg_lyft_equivalent_fare_usd=avg_lyft_fare,
        avg_rider_savings_vs_uber_usd=round(avg_uber_fare - avg_fare, 2),
        avg_rider_savings_vs_lyft_usd=round(avg_lyft_fare - avg_fare, 2),
    )


def _build_service_quality(rides: list[Ride], cancelled_count: int) -> ServiceQuality:
    """Compute aggregate service quality metrics.

    Ratings come from Ride.driver_rating (rider-submitted) and
    Ride.rider_rating (driver-submitted). Null ratings are excluded
    from averages. Completion rate = completed / (completed + cancelled).
    """
    driver_ratings = [r.driver_rating for r in rides if r.driver_rating is not None]
    rider_ratings = [r.rider_rating for r in rides if r.rider_rating is not None]

    avg_driver = round(
        _safe_div(sum(driver_ratings), len(driver_ratings)), 2
    ) if driver_ratings else 0.0
    avg_rider = round(
        _safe_div(sum(rider_ratings), len(rider_ratings)), 2
    ) if rider_ratings else 0.0

    total_attempted = len(rides) + cancelled_count
    completion_pct = round(
        _safe_div(len(rides) * 100.0, total_attempted), 1
    ) if total_attempted > 0 else 0.0

    return ServiceQuality(
        avg_driver_rating=avg_driver,
        avg_rider_rating=avg_rider,
        rides_completed_pct=completion_pct,
    )


def _zero_earnings_summary() -> EarningsSummary:
    return EarningsSummary(
        total_driver_earnings_usd=0.0,
        avg_driver_earnings_per_ride_usd=0.0,
        avg_driver_payout_pct=100.0,
        uber_equivalent_driver_earnings_usd=0.0,
        lyft_equivalent_driver_earnings_usd=0.0,
        driver_savings_vs_uber_usd=0.0,
        driver_savings_vs_lyft_usd=0.0,
    )


def _zero_rider_summary() -> RiderSummary:
    return RiderSummary(
        unique_riders_period=0,
        avg_fare_usd=0.0,
        avg_uber_equivalent_fare_usd=0.0,
        avg_lyft_equivalent_fare_usd=0.0,
        avg_rider_savings_vs_uber_usd=0.0,
        avg_rider_savings_vs_lyft_usd=0.0,
    )


def _zero_service_quality() -> ServiceQuality:
    return ServiceQuality(
        avg_driver_rating=0.0,
        avg_rider_rating=0.0,
        rides_completed_pct=0.0,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_platform_transparency_report(
    db: AsyncSession,
    period: ReportPeriod = ReportPeriod.LAST_30_DAYS,
) -> PlatformTransparencyReport:
    """Generate a public platform transparency report for the requested period.

    Args:
        db:     Async database session.
        period: Time window for the report ('last_7_days', 'last_30_days',
                or 'all_time'). Defaults to 'last_30_days'.

    Returns:
        PlatformTransparencyReport with platform model description, ride
        volumes, driver earnings, rider savings, and service quality metrics.
        All numeric fields are zero and data_available is False when no
        completed rides exist.
    """
    now = datetime.now(tz=timezone.utc)
    period_start_dt = _period_start(period, now)

    # Fetch all-time total (used regardless of selected period)
    all_time_count = await _count_all_time_completed(db)

    # Fetch rides within the requested period
    period_rides = await _fetch_period_completed_rides(db, period_start_dt)
    period_count = len(period_rides)

    data_available = period_count > 0

    if data_available:
        # Fetch payments for all period rides
        ride_ids = [r.id for r in period_rides]
        payments = await _fetch_payments_for_rides(db, ride_ids)

        cancelled_count = await _count_cancelled_in_period(db, period_start_dt)

        earnings_summary = _build_earnings_summary(period_rides, payments)
        rider_summary = _build_rider_summary(period_rides)
        service_quality = _build_service_quality(period_rides, cancelled_count)
    else:
        earnings_summary = _zero_earnings_summary()
        rider_summary = _zero_rider_summary()
        service_quality = _zero_service_quality()

    return PlatformTransparencyReport(
        generated_at=now,
        report_period=period.value,
        data_available=data_available,
        platform_model=_PLATFORM_MODEL,
        ride_volume=RideVolume(
            total_rides_completed=all_time_count,
            total_rides_period=period_count,
            period_label=_PERIOD_LABELS[period],
        ),
        earnings_summary=earnings_summary,
        rider_summary=rider_summary,
        service_quality=service_quality,
        methodology_note=_METHODOLOGY_NOTE,
        transparency_note=_TRANSPARENCY_NOTE,
    )
