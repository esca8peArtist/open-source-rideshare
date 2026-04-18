"""Pydantic schema for GET /rides/eta/estimate — public pre-booking ETA endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ETAEstimateResponse(BaseModel):
    """Pre-booking ETA estimate returned to the rider app before they confirm a ride.

    All time values are in whole minutes.  The confidence field lets the UI
    communicate data quality to the rider — a "low" confidence estimate means
    no drivers were found nearby and a static fallback was used.
    """

    pickup_eta_minutes: int = Field(
        ...,
        ge=1,
        description=(
            "Estimated minutes until the nearest available driver reaches the pickup. "
            "Calculated as ceil(nearest_driver_distance_km / 30 km/h). "
            "Falls back to 15 when no drivers are available within 10 km."
        ),
    )
    trip_duration_minutes: int = Field(
        ...,
        ge=2,
        description=(
            "Estimated ride duration from pickup to dropoff in whole minutes. "
            "Calculated as ceil(haversine_distance / 30 km/h), minimum 2 minutes."
        ),
    )
    nearest_driver_distance_km: float | None = Field(
        ...,
        description=(
            "Straight-line distance in kilometres to the closest available driver. "
            "Null when no drivers are found within the 10 km search radius."
        ),
    )
    available_driver_count: int = Field(
        ...,
        ge=0,
        description="Number of available drivers found within 10 km of the pickup location.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "Estimate confidence level based on driver availability: "
            "'high' = 3 or more drivers nearby, "
            "'medium' = 1–2 drivers nearby, "
            "'low' = no drivers found (fallback values used)."
        ),
    )
