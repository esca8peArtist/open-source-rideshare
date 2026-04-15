"""Pydantic schemas for the driver work preferences API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class DriverWorkPreferenceUpdate(BaseModel):
    """Request body for creating or updating driver work preferences.

    All fields are optional so callers can perform partial updates.
    Distance bounds are validated: if both are provided, min <= max is required.
    """

    accept_pool_rides: bool | None = None
    accept_pet_riders: bool | None = None
    accept_extra_luggage: bool | None = None
    min_trip_distance_km: float | None = Field(None, ge=0.0, le=500.0)
    max_trip_distance_km: float | None = Field(None, ge=0.0, le=500.0)
    prefer_long_distance: bool | None = None
    prefer_language_matched: bool | None = None
    notes: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def validate_distance_range(self) -> "DriverWorkPreferenceUpdate":
        """Ensure min_trip_distance_km <= max_trip_distance_km when both are set."""
        if (
            self.min_trip_distance_km is not None
            and self.max_trip_distance_km is not None
            and self.min_trip_distance_km > self.max_trip_distance_km
        ):
            raise ValueError(
                "min_trip_distance_km must be less than or equal to max_trip_distance_km"
            )
        return self


class DriverWorkPreferenceResponse(BaseModel):
    """Driver work preferences as returned by the API."""

    driver_id: int
    accept_pool_rides: bool
    accept_pet_riders: bool
    accept_extra_luggage: bool
    min_trip_distance_km: float | None
    max_trip_distance_km: float | None
    prefer_long_distance: bool
    prefer_language_matched: bool
    notes: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}
