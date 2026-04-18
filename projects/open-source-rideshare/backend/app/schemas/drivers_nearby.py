"""Pydantic schemas for GET /drivers/nearby — public pre-booking endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NearbyDriverEntry(BaseModel):
    """One nearby available driver returned to a rider before booking.

    Privacy rules:
    - driver_id is the opaque DriverProfile primary key (int UUID surrogate).
      No name, phone, or other PII is included.
    - Exact coordinates are NOT returned — only derived distance and ETA.
    """

    driver_id: int = Field(..., description="Opaque driver profile identifier")
    eta_minutes: int = Field(
        ..., ge=0, description="Rough ETA in whole minutes (distance / 30 km/h)"
    )
    distance_km: float = Field(
        ..., ge=0.0, description="Straight-line distance from rider to driver in kilometres"
    )
    vehicle_type: str | None = Field(
        None, description="Vehicle category (e.g. 'sedan', 'suv'), or null if not set"
    )


class DriversNearbyResponse(BaseModel):
    """Response envelope for GET /drivers/nearby."""

    drivers: list[NearbyDriverEntry] = Field(
        ..., description="Available drivers sorted by distance ascending, capped at 20"
    )
    count: int = Field(..., ge=0, description="Number of drivers returned")
    radius_km: float = Field(..., gt=0, description="Effective search radius used")
