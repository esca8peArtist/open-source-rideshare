"""Ride carbon footprint service layer.

Public functions:
  calculate_co2           — pure function: g CO2 for an emission class + distance
  calculate_offset_cost   — pure function: offset cost in cents for g CO2
  record_ride_carbon      — create/upsert carbon record for a completed ride
  get_ride_carbon         — fetch carbon record by ride_id
  pay_carbon_offset       — mark a record as offset-paid
  get_rider_carbon_summary — aggregate stats for a rider
  get_platform_carbon_stats — platform-wide sustainability metrics
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride_carbon import (
    EMISSION_RATES_G_PER_KM,
    OFFSET_CENTS_PER_KG,
    RideCarbonRecord,
    VehicleEmissionClass,
)
from app.schemas.ride_carbon import PlatformCarbonStats, RiderCarbonSummary


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class CarbonError(Exception):
    """Business-rule violations in the carbon footprint service."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Pure calculation helpers
# ---------------------------------------------------------------------------


def calculate_co2(emission_class: VehicleEmissionClass, distance_km: float) -> int:
    """Return CO2 in grams for the given emission class and distance.

    Rounds to the nearest gram.  Always >= 0.
    """
    rate = EMISSION_RATES_G_PER_KM.get(emission_class, EMISSION_RATES_G_PER_KM[VehicleEmissionClass.unknown])
    return max(0, round(rate * distance_km))


def calculate_offset_cost_cents(co2_grams: int) -> int:
    """Return voluntary carbon offset cost in US cents.

    Pricing: $1 per 10 kg CO2 = 10 cents per 1,000 g.
    Minimum 1 cent if there are any emissions at all.
    """
    if co2_grams <= 0:
        return 0
    cents = round(co2_grams * OFFSET_CENTS_PER_KG / 1000)
    return max(1, cents)


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


async def record_ride_carbon(
    db: AsyncSession,
    ride_id: int,
    emission_class: VehicleEmissionClass,
    distance_km: float,
) -> RideCarbonRecord:
    """Create (or overwrite) the carbon record for a completed ride.

    Idempotent: calling twice for the same ride_id updates the existing row
    rather than raising a duplicate-key error.  Offset status is preserved
    if already paid.
    """
    if distance_km <= 0:
        raise CarbonError("distance_km must be positive")

    co2 = calculate_co2(emission_class, distance_km)
    offset_cost = calculate_offset_cost_cents(co2)

    result = await db.execute(
        select(RideCarbonRecord).where(RideCarbonRecord.ride_id == ride_id)
    )
    record = result.scalar_one_or_none()

    if record is None:
        record = RideCarbonRecord(
            ride_id=ride_id,
            emission_class=emission_class,
            distance_km=distance_km,
            co2_grams=co2,
            offset_cost_cents=offset_cost,
            offset_paid=False,
            offset_amount_cents=0,
        )
        db.add(record)
    else:
        # Update fields but preserve offset payment if already completed
        record.emission_class = emission_class
        record.distance_km = distance_km
        record.co2_grams = co2
        record.offset_cost_cents = offset_cost

    await db.commit()
    await db.refresh(record)
    return record


async def get_ride_carbon(
    db: AsyncSession, ride_id: int
) -> RideCarbonRecord | None:
    """Return the carbon record for a ride, or None if not yet recorded."""
    result = await db.execute(
        select(RideCarbonRecord).where(RideCarbonRecord.ride_id == ride_id)
    )
    return result.scalar_one_or_none()


async def pay_carbon_offset(
    db: AsyncSession,
    ride_id: int,
    rider_id: int,
) -> RideCarbonRecord:
    """Mark the carbon record for a ride as offset-paid.

    The rider_id is accepted for authorization checks at the API layer;
    the service records the timestamp and amount.

    Raises CarbonError(404) if no carbon record exists for the ride.
    Raises CarbonError(409) if already paid.
    """
    record = await get_ride_carbon(db, ride_id)
    if record is None:
        raise CarbonError("No carbon record found for this ride", status_code=404)
    if record.offset_paid:
        raise CarbonError("Carbon offset already paid for this ride", status_code=409)

    record.offset_paid = True
    record.offset_amount_cents = record.offset_cost_cents
    record.offset_paid_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(record)
    return record


async def get_rider_carbon_summary(
    db: AsyncSession, rider_id: int
) -> RiderCarbonSummary:
    """Return aggregate carbon stats for a rider across all their rides.

    Joins ride_carbon_records → rides → rider_id.  Returns zero-value
    summary for riders with no carbon data.
    """
    from app.models.ride import Ride  # local import to avoid circular

    q = (
        select(RideCarbonRecord)
        .join(Ride, Ride.id == RideCarbonRecord.ride_id)
        .where(Ride.rider_id == rider_id)
    )
    result = await db.execute(q)
    records = result.scalars().all()

    total_co2 = sum(r.co2_grams for r in records)
    total_dist = sum(r.distance_km for r in records)
    offsets_paid = [r for r in records if r.offset_paid]

    counts: dict[str, int] = {
        VehicleEmissionClass.petrol: 0,
        VehicleEmissionClass.diesel: 0,
        VehicleEmissionClass.hybrid: 0,
        VehicleEmissionClass.electric: 0,
    }
    for r in records:
        key = r.emission_class if r.emission_class in counts else VehicleEmissionClass.petrol
        counts[key] += 1

    n = len(records)
    return RiderCarbonSummary(
        rider_id=rider_id,
        total_rides_tracked=n,
        total_co2_grams=total_co2,
        total_co2_kg=round(total_co2 / 1000, 3),
        total_distance_km=round(total_dist, 3),
        offsets_paid_count=len(offsets_paid),
        total_offset_cost_cents=sum(r.offset_cost_cents for r in records),
        total_offset_paid_cents=sum(r.offset_amount_cents for r in offsets_paid),
        avg_co2_per_ride_grams=round(total_co2 / n, 1) if n > 0 else 0.0,
        petrol_rides=counts[VehicleEmissionClass.petrol],
        diesel_rides=counts[VehicleEmissionClass.diesel],
        hybrid_rides=counts[VehicleEmissionClass.hybrid],
        electric_rides=counts[VehicleEmissionClass.electric],
    )


async def get_platform_carbon_stats(db: AsyncSession) -> PlatformCarbonStats:
    """Return platform-wide sustainability metrics (admin only)."""
    result = await db.execute(select(RideCarbonRecord))
    records = result.scalars().all()

    n = len(records)
    total_co2 = sum(r.co2_grams for r in records)
    total_dist = sum(r.distance_km for r in records)
    offsets_paid = [r for r in records if r.offset_paid]

    class_counts: dict[str, int] = {
        VehicleEmissionClass.petrol: 0,
        VehicleEmissionClass.diesel: 0,
        VehicleEmissionClass.hybrid: 0,
        VehicleEmissionClass.electric: 0,
    }
    for r in records:
        key = r.emission_class
        if key in class_counts:
            class_counts[key] += 1
        else:
            class_counts[VehicleEmissionClass.petrol] += 1

    electric = class_counts[VehicleEmissionClass.electric]
    hybrid = class_counts[VehicleEmissionClass.hybrid]
    green = electric + hybrid

    return PlatformCarbonStats(
        total_rides_tracked=n,
        total_co2_grams=total_co2,
        total_co2_kg=round(total_co2 / 1000, 3),
        total_distance_km=round(total_dist, 3),
        offsets_paid_count=len(offsets_paid),
        total_offset_revenue_cents=sum(r.offset_amount_cents for r in offsets_paid),
        total_offset_revenue_dollars=round(sum(r.offset_amount_cents for r in offsets_paid) / 100, 2),
        electric_rides=electric,
        hybrid_rides=hybrid,
        petrol_rides=class_counts[VehicleEmissionClass.petrol],
        diesel_rides=class_counts[VehicleEmissionClass.diesel],
        electric_pct=round(electric / n * 100, 1) if n > 0 else 0.0,
        green_pct=round(green / n * 100, 1) if n > 0 else 0.0,
    )
