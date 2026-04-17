"""Pre-booking fare transparency service.

Produces a full fare breakdown — OpenRide cost, driver payout, platform fee,
and competitor comparison (Uber/Lyft) — given trip distance and duration.

No database access is required; all computation is deterministic based on
the pricing model and published competitor rate cards.

Public API
----------
  get_fare_preview(distance_km, duration_min, surge_multiplier)
      → FarePreviewResponse
"""

from __future__ import annotations

from app.schemas.fare_preview import FarePreviewCompetitor, FarePreviewResponse
from app.services.pricing import calculate_fare_breakdown

# ---------------------------------------------------------------------------
# Competitor rate cards (2025 US national averages)
# Source: RideGuru national average rate survey; rideshare driver community
# aggregates.  Rates vary significantly by city, time, and surge conditions.
# These are illustrative national averages documented for transparency.
# ---------------------------------------------------------------------------

_KM_TO_MILES: float = 0.621371

# Uber UberX — 2025 national average
_UBER_BASE_FARE: float = 1.38       # USD
_UBER_PER_MIN: float = 0.20         # USD / minute
_UBER_PER_MILE: float = 0.84        # USD / mile
_UBER_DRIVER_TAKE_RATE: float = 0.75  # driver keeps ~75% after ~25% Uber commission
_UBER_PLATFORM_RATE: float = 0.25
_UBER_PLATFORM_NAME: str = "Uber (UberX)"
_UBER_SOURCE_NOTE: str = (
    "2025 US national average for UberX. Driver take rate ~75% after Uber's ~25% "
    "service fee. Source: RideGuru national average rate survey, rideshare driver "
    "community aggregates. Actual rates vary by city, time of day, and surge conditions."
)

# Lyft Standard — 2025 national average
_LYFT_BASE_FARE: float = 1.25       # USD
_LYFT_PER_MIN: float = 0.22         # USD / minute
_LYFT_PER_MILE: float = 0.83        # USD / mile
_LYFT_DRIVER_TAKE_RATE: float = 0.75  # driver keeps ~75% after ~25% Lyft commission
_LYFT_PLATFORM_RATE: float = 0.25
_LYFT_PLATFORM_NAME: str = "Lyft (Standard)"
_LYFT_SOURCE_NOTE: str = (
    "2025 US national average for Lyft Standard. Driver take rate ~75% after Lyft's "
    "~25% service fee. Source: RideGuru national average rate survey, rideshare driver "
    "community aggregates. Actual rates vary by city, time of day, and surge conditions."
)

_METHODOLOGY_NOTE: str = (
    "OpenRide fare computed from live pricing parameters (base fare + per-km rate "
    "+ per-minute rate × any surge multiplier). Platform fee is 0% — the cooperative "
    "charges no commission. Competitor fares are estimates based on 2025 US national "
    "average rate cards for UberX and Lyft Standard and are for informational purposes "
    "only; actual competitor fares vary significantly by city and conditions."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _competitor_estimate(
    distance_km: float,
    duration_min: float,
    base_fare: float,
    per_min: float,
    per_mile: float,
    driver_take_rate: float,
    platform_rate: float,
    platform_name: str,
    source_note: str,
) -> FarePreviewCompetitor:
    """Estimate fare and driver payout for a competitor platform."""
    distance_miles = distance_km * _KM_TO_MILES
    estimated_fare = round(base_fare + per_min * duration_min + per_mile * distance_miles, 2)
    driver_payout = round(estimated_fare * driver_take_rate, 2)
    platform_fee = round(estimated_fare * platform_rate, 2)
    return FarePreviewCompetitor(
        platform_name=platform_name,
        estimated_fare_usd=estimated_fare,
        estimated_driver_payout_usd=driver_payout,
        estimated_driver_payout_pct=round(driver_take_rate * 100, 1),
        estimated_platform_fee_usd=platform_fee,
        estimated_platform_fee_pct=round(platform_rate * 100, 1),
        source_note=source_note,
    )


def _build_transparency_note(
    driver_payout_usd: float,
    driver_payout_pct: float,
    uber: FarePreviewCompetitor,
    lyft: FarePreviewCompetitor,
) -> str:
    """Human-readable summary of the fare split for the rider app UI."""
    uber_driver_pct = uber.estimated_driver_payout_pct
    lyft_driver_pct = lyft.estimated_driver_payout_pct

    return (
        f"On OpenRide, your driver keeps {driver_payout_pct:.0f}% of the fare "
        f"(${driver_payout_usd:.2f}) — compared to ~{uber_driver_pct:.0f}% on Uber "
        f"and ~{lyft_driver_pct:.0f}% on Lyft. OpenRide charges no platform commission."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_fare_preview(
    distance_km: float,
    duration_min: float,
    surge_multiplier: float = 1.0,
) -> FarePreviewResponse:
    """Compute a pre-booking fare transparency preview.

    Args:
        distance_km:      Trip distance in kilometres (> 0).
        duration_min:     Estimated trip duration in minutes (> 0).
        surge_multiplier: Surge zone multiplier in effect at pickup (≥ 1.0).
                          Pass the value returned by GET /pricing/surge-check.

    Returns:
        FarePreviewResponse with OpenRide fare, driver payout, platform fee,
        competitor comparisons, and transparency/methodology notes.
    """
    bd = calculate_fare_breakdown(
        distance_km,
        duration_min,
        surge_multiplier=surge_multiplier,
    )

    openride_fare = bd.total
    platform_fee = bd.platform_fee  # 0.0 with default zero-commission config
    driver_payout = round(openride_fare - platform_fee, 2)

    if openride_fare > 0:
        driver_payout_pct = round((driver_payout / openride_fare) * 100, 1)
        platform_fee_pct = round((platform_fee / openride_fare) * 100, 1)
    else:
        driver_payout_pct = 100.0
        platform_fee_pct = 0.0

    uber = _competitor_estimate(
        distance_km=distance_km,
        duration_min=duration_min,
        base_fare=_UBER_BASE_FARE,
        per_min=_UBER_PER_MIN,
        per_mile=_UBER_PER_MILE,
        driver_take_rate=_UBER_DRIVER_TAKE_RATE,
        platform_rate=_UBER_PLATFORM_RATE,
        platform_name=_UBER_PLATFORM_NAME,
        source_note=_UBER_SOURCE_NOTE,
    )

    lyft = _competitor_estimate(
        distance_km=distance_km,
        duration_min=duration_min,
        base_fare=_LYFT_BASE_FARE,
        per_min=_LYFT_PER_MIN,
        per_mile=_LYFT_PER_MILE,
        driver_take_rate=_LYFT_DRIVER_TAKE_RATE,
        platform_rate=_LYFT_PLATFORM_RATE,
        platform_name=_LYFT_PLATFORM_NAME,
        source_note=_LYFT_SOURCE_NOTE,
    )

    driver_more_uber = round(driver_payout - uber.estimated_driver_payout_usd, 2)
    driver_more_lyft = round(driver_payout - lyft.estimated_driver_payout_usd, 2)

    transparency_note = _build_transparency_note(
        driver_payout_usd=driver_payout,
        driver_payout_pct=driver_payout_pct,
        uber=uber,
        lyft=lyft,
    )

    return FarePreviewResponse(
        distance_km=round(distance_km, 3),
        duration_min=round(duration_min, 1),
        surge_multiplier=round(surge_multiplier, 2),
        is_surge=surge_multiplier > 1.0,
        estimated_fare_usd=openride_fare,
        driver_payout_usd=driver_payout,
        driver_payout_pct=driver_payout_pct,
        platform_fee_usd=round(platform_fee, 2),
        platform_fee_pct=platform_fee_pct,
        uber_estimate=uber,
        lyft_estimate=lyft,
        driver_earns_more_than_uber_usd=driver_more_uber,
        driver_earns_more_than_lyft_usd=driver_more_lyft,
        transparency_note=transparency_note,
        methodology_note=_METHODOLOGY_NOTE,
    )
