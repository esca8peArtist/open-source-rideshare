"""Rider fare transparency service.

Returns a per-ride breakdown showing the rider exactly where their money went:
driver payout, platform fee, tips, and taxes — with a side-by-side comparison
to estimated Uber/Lyft platform fees for the same fare.

Public API:
  get_fare_breakdown(db, ride_id, current_user)
      → FareBreakdownResponse

Platform fee handling:
  OpenRide stores a `platform_fee` column on every Payment record. When a
  completed Payment record exists for the ride, the actual stored value is used.
  When no Payment record exists (cash rides, legacy records), the service falls
  back to the documented standard rate constant below and sets
  `platform_fee_is_estimated = True` in the response so the caller can
  surface appropriate UI copy.

  Current OpenRide standard rate: 10% of fare (excluding tips).
  Source: internal pricing policy, 2025. Uber ~25-28%, Lyft ~20-25% (2025
  US national averages, RideGuru / community driver surveys).

Authorization:
  - Riders may only access their own rides.
  - Admins may access any ride.
  - Drivers are not the intended audience for this endpoint; use
    /drivers/me/earnings-comparison for driver-facing transparency.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.rider_fare_transparency import (
    CompetitorFeeComparison,
    FareBreakdownResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform fee constants
# ---------------------------------------------------------------------------

# OpenRide's documented standard platform fee rate.
# Applied only when no per-ride Payment record is available.
# Update this constant whenever the cooperative votes to change the rate.
OPENRIDE_PLATFORM_FEE_RATE: float = 0.10  # 10% of base fare (excl. tips)

# ---------------------------------------------------------------------------
# 2025 competitor take rates (platform fee as fraction of gross fare)
# Source: RideGuru national average rate survey, driver community aggregates.
# These are the platform's cut — the rider's complement goes to the driver.
# ---------------------------------------------------------------------------

# Uber takes ~25-28% of gross fare as its service fee.
_UBER_PLATFORM_FEE_RATE_LOW: float = 0.25
_UBER_PLATFORM_FEE_RATE_HIGH: float = 0.28
# Use midpoint for the comparison estimate.
_UBER_PLATFORM_FEE_RATE: float = (_UBER_PLATFORM_FEE_RATE_LOW + _UBER_PLATFORM_FEE_RATE_HIGH) / 2

# Lyft takes ~20-25% of gross fare as its service fee.
_LYFT_PLATFORM_FEE_RATE_LOW: float = 0.20
_LYFT_PLATFORM_FEE_RATE_HIGH: float = 0.25
_LYFT_PLATFORM_FEE_RATE: float = (_LYFT_PLATFORM_FEE_RATE_LOW + _LYFT_PLATFORM_FEE_RATE_HIGH) / 2

_UBER_SOURCE_NOTE = (
    "2025 US national average. Uber's service fee is ~25–28% of gross fare, "
    "leaving ~72–75% for the driver. Source: RideGuru national average rate survey, "
    "rideshare driver community aggregates. Actual rates vary by city and surge."
)

_LYFT_SOURCE_NOTE = (
    "2025 US national average. Lyft's service fee is ~20–25% of gross fare, "
    "leaving ~75–80% for the driver. Source: RideGuru national average rate survey, "
    "rideshare driver community aggregates. Actual rates vary by city and surge."
)

_METHODOLOGY_NOTE = (
    "Competitor platform fee estimates are based on published 2025 US national average "
    "take rates for Uber (25–28%) and Lyft (20–25%). Actual competitor fees vary "
    "significantly by city, time of day, surge conditions, and driver incentive programs. "
    "This comparison is for informational purposes only."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_pct(part: float, total: float) -> float:
    """Return (part / total) * 100 rounded to 2 dp. Returns 0.0 when total is zero."""
    if total == 0.0:
        return 0.0
    return round((part / total) * 100.0, 2)


def _build_competitor_comparison(
    platform_name: str,
    fee_rate: float,
    base_fare: float,
    source_note: str,
) -> CompetitorFeeComparison:
    """Build a CompetitorFeeComparison for a given platform and base fare amount.

    Tips are excluded from the fee base: tips go 100% to the driver on all
    platforms (or are handled separately), so we only charge the platform fee
    against the non-tip portion of the fare.
    """
    estimated_fee = round(base_fare * fee_rate, 2)
    estimated_driver_payout = round(base_fare * (1.0 - fee_rate), 2)
    return CompetitorFeeComparison(
        platform_name=platform_name,
        platform_fee_rate=fee_rate,
        estimated_platform_fee_usd=estimated_fee,
        estimated_driver_payout_usd=estimated_driver_payout,
        source_note=source_note,
    )


def _build_transparency_note(
    total_fare: float,
    driver_payout: float,
    driver_pct: float,
    platform_fee: float,
    platform_pct: float,
    tip: float,
    is_estimated: bool,
) -> str:
    """Generate a human-readable transparency note for the rider app."""
    estimated_qualifier = " (estimated at standard rate)" if is_estimated else ""
    tip_line = f" Your ${tip:.2f} tip goes entirely to the driver." if tip > 0 else ""
    return (
        f"Of your ${total_fare:.2f} fare, ${driver_payout:.2f} "
        f"({driver_pct:.1f}%) went directly to your driver and "
        f"${platform_fee:.2f} ({platform_pct:.1f}%) was OpenRide's platform fee"
        f"{estimated_qualifier}.{tip_line} "
        "OpenRide operates as a driver cooperative and keeps its platform fee "
        "lower than traditional rideshare apps, so more of every fare reaches "
        "the people doing the work."
    )


# ---------------------------------------------------------------------------
# Database fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_ride(db: AsyncSession, ride_id: int) -> Ride | None:
    """Fetch a ride by ID regardless of status."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    return result.scalar_one_or_none()


async def _fetch_payment(db: AsyncSession, ride_id: int) -> Payment | None:
    """Fetch the completed RIDE_FARE Payment for a ride, if any."""
    result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride_id,
            Payment.payment_type == PaymentType.RIDE_FARE,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


async def get_fare_breakdown(
    db: AsyncSession,
    ride_id: int,
    current_user: User,
) -> FareBreakdownResponse:
    """Return a detailed fare breakdown for a single completed ride.

    Args:
        db:           Database session.
        ride_id:      The ride to inspect.
        current_user: The authenticated user making the request.

    Returns:
        FareBreakdownResponse with fare components and competitor comparison.

    Raises:
        HTTPException 404: Ride not found or not completed.
        HTTPException 403: Rider attempting to access another rider's fare.
    """
    ride = await _fetch_ride(db, ride_id)

    if ride is None or ride.status != RideStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found.",
        )

    # Authorization: riders can only see their own rides; admins see all.
    if current_user.role != UserRole.ADMIN and ride.rider_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this fare breakdown.",
        )

    # -----------------------------------------------------------------------
    # Determine fare components
    # -----------------------------------------------------------------------

    # Total fare paid by rider
    total_fare = float(ride.actual_fare or ride.estimated_fare or 0.0)

    # Tip is stored on the Ride row (kept in sync by the tip service)
    tip = float(ride.tip_amount or 0.0)

    # Base fare excludes tip for platform fee calculation purposes
    base_fare = max(total_fare - tip, 0.0)

    # -----------------------------------------------------------------------
    # Platform fee: prefer Payment record, fall back to constant
    # -----------------------------------------------------------------------

    payment = await _fetch_payment(db, ride_id)
    platform_fee_is_estimated = False

    if payment is not None:
        # Use the actual stored platform fee and driver payout.
        platform_fee = float(payment.platform_fee)
        driver_payout = float(payment.driver_payout)
        # Derive the effective rate from the stored values to show in the response.
        # Avoid division-by-zero for zero-fare rides.
        if base_fare > 0:
            openride_rate_used = round(platform_fee / base_fare, 6)
        else:
            openride_rate_used = 0.0
    else:
        # No completed payment record — estimate using the standard rate.
        platform_fee_is_estimated = True
        openride_rate_used = OPENRIDE_PLATFORM_FEE_RATE
        platform_fee = round(base_fare * OPENRIDE_PLATFORM_FEE_RATE, 2)
        # Driver payout = base_fare minus platform fee, plus the tip.
        driver_payout = round(base_fare - platform_fee + tip, 2)

    platform_fee = round(platform_fee, 2)
    driver_payout = round(driver_payout, 2)
    total_fare = round(total_fare, 2)

    # Taxes: not currently tracked per-ride; surfaced as 0.00 for transparency.
    taxes_usd = 0.0
    taxes_pct = 0.0

    # -----------------------------------------------------------------------
    # Percentages
    # -----------------------------------------------------------------------

    driver_pct = _safe_pct(driver_payout, total_fare)
    platform_pct = _safe_pct(platform_fee, total_fare)

    # -----------------------------------------------------------------------
    # Competitor comparisons (based on base_fare — same logic: tips excluded)
    # -----------------------------------------------------------------------

    uber_comparison = _build_competitor_comparison(
        platform_name="Uber (UberX)",
        fee_rate=_UBER_PLATFORM_FEE_RATE,
        base_fare=base_fare,
        source_note=_UBER_SOURCE_NOTE,
    )
    lyft_comparison = _build_competitor_comparison(
        platform_name="Lyft (Standard)",
        fee_rate=_LYFT_PLATFORM_FEE_RATE,
        base_fare=base_fare,
        source_note=_LYFT_SOURCE_NOTE,
    )

    # OpenRide driver advantage: how much more the driver received vs. competitors.
    driver_more_than_uber = round(driver_payout - uber_comparison.estimated_driver_payout_usd, 2)
    driver_more_than_lyft = round(driver_payout - lyft_comparison.estimated_driver_payout_usd, 2)

    # -----------------------------------------------------------------------
    # Human-readable note
    # -----------------------------------------------------------------------

    transparency_note = _build_transparency_note(
        total_fare=total_fare,
        driver_payout=driver_payout,
        driver_pct=driver_pct,
        platform_fee=platform_fee,
        platform_pct=platform_pct,
        tip=tip,
        is_estimated=platform_fee_is_estimated,
    )

    return FareBreakdownResponse(
        ride_id=ride_id,
        total_fare_usd=total_fare,
        driver_payout_usd=driver_payout,
        driver_payout_pct=driver_pct,
        platform_fee_usd=platform_fee,
        platform_fee_pct=platform_pct,
        tip_usd=tip,
        taxes_usd=taxes_usd,
        taxes_pct=taxes_pct,
        platform_fee_is_estimated=platform_fee_is_estimated,
        openride_platform_fee_rate_used=openride_rate_used,
        uber_comparison=uber_comparison,
        lyft_comparison=lyft_comparison,
        driver_received_more_than_uber_usd=driver_more_than_uber,
        driver_received_more_than_lyft_usd=driver_more_than_lyft,
        transparency_note=transparency_note,
        methodology_note=_METHODOLOGY_NOTE,
    )
