"""Pydantic schemas for GET /drivers/{driver_id}/public-profile.

Exposes only non-PII, rider-relevant driver data for the pre-booking
confirmation step.

Deliberately excluded fields:
  - license_plate, license_number  (sensitive / PII)
  - insurance_policy               (sensitive)
  - user_id, current_location      (PII / exact location)
  - is_online                      (real-time availability handled by /drivers/nearby)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DriverPublicProfile(BaseModel):
    """Public-facing driver profile shown to riders before confirming a booking."""

    driver_id: int = Field(..., description="Opaque DriverProfile primary key")
    vehicle_type: str = Field(..., description="Vehicle category (e.g. 'sedan', 'suv')")
    vehicle_make: str = Field(..., description="Manufacturer (e.g. 'Toyota')")
    vehicle_model: str = Field(..., description="Model name (e.g. 'Camry')")
    vehicle_year: int = Field(..., description="Model year")
    vehicle_color: str = Field(..., description="Exterior color")
    rating_avg: float = Field(..., ge=1.0, le=5.0, description="Lifetime average rating (1–5)")
    total_trips: int = Field(..., ge=0, description="Total completed trips")
    is_approved: bool = Field(
        ...,
        description="Whether the driver has passed background check and platform approval",
    )
    member_since: datetime = Field(..., description="When the driver joined the platform")

    model_config = {"from_attributes": True}
