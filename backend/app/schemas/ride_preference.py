"""Pydantic schemas for the ride preferences API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.ride_preference import TemperaturePreference


class RidePreferenceUpdate(BaseModel):
    """Request body for creating or updating ride preferences.

    All fields are optional so callers can do partial updates.
    """

    quiet_ride: bool | None = None
    music_off: bool | None = None
    temperature_preference: TemperaturePreference | None = None
    pet_friendly: bool | None = None
    extra_luggage: bool | None = None
    accessibility_vehicle_needed: bool | None = None
    notes: str | None = Field(None, max_length=200)


class RidePreferenceResponse(BaseModel):
    """Ride preferences as returned by the API."""

    user_id: int
    quiet_ride: bool
    music_off: bool
    temperature_preference: TemperaturePreference
    pet_friendly: bool
    extra_luggage: bool
    accessibility_vehicle_needed: bool
    notes: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}
