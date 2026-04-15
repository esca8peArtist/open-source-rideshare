"""Pydantic schemas for Ride Carbon Footprint endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.ride_carbon import VehicleEmissionClass


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RecordRideCarbonRequest(BaseModel):
    """Admin/internal request to record carbon data for a completed ride."""

    ride_id: int
    emission_class: VehicleEmissionClass = VehicleEmissionClass.unknown
    distance_km: float = Field(..., gt=0, description="Distance in kilometres")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class RideCarbonResponse(BaseModel):
    """Full carbon record for a single ride."""

    model_config = {"from_attributes": True}

    id: int
    ride_id: int
    emission_class: VehicleEmissionClass
    distance_km: float
    co2_grams: int
    offset_cost_cents: int
    offset_paid: bool
    offset_amount_cents: int
    created_at: datetime
    offset_paid_at: datetime | None = None

    # Human-readable helpers (not stored, computed in response)
    co2_kg: float = 0.0
    offset_cost_dollars: float = 0.0

    @classmethod
    def from_record(cls, record: object) -> "RideCarbonResponse":
        obj = cls.model_validate(record)
        obj.co2_kg = round(obj.co2_grams / 1000, 3)
        obj.offset_cost_dollars = round(obj.offset_cost_cents / 100, 2)
        return obj


class RiderCarbonSummary(BaseModel):
    """Aggregate carbon footprint for a rider across all their rides."""

    rider_id: int
    total_rides_tracked: int
    total_co2_grams: int
    total_co2_kg: float
    total_distance_km: float
    offsets_paid_count: int
    total_offset_cost_cents: int
    total_offset_paid_cents: int
    avg_co2_per_ride_grams: float
    # Breakdown by emission class
    petrol_rides: int
    diesel_rides: int
    hybrid_rides: int
    electric_rides: int


class PlatformCarbonStats(BaseModel):
    """Platform-wide sustainability metrics (admin only)."""

    total_rides_tracked: int
    total_co2_grams: int
    total_co2_kg: float
    total_distance_km: float
    offsets_paid_count: int
    total_offset_revenue_cents: int
    total_offset_revenue_dollars: float
    electric_rides: int
    hybrid_rides: int
    petrol_rides: int
    diesel_rides: int
    electric_pct: float
    green_pct: float  # electric + hybrid combined
