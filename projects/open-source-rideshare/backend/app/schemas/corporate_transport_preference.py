"""Pydantic schemas for Corporate Employee Transport Preferences."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Recognised accessibility-need tags (informational — not an enum to keep
# the field extensible without requiring a migration for new tags).
# ---------------------------------------------------------------------------

KNOWN_ACCESSIBILITY_NEEDS = frozenset(
    {
        "wheelchair_accessible",
        "service_animal",
        "extra_boarding_time",
        "front_seat_required",
        "audio_assistance",
    }
)

KNOWN_VEHICLE_TYPES = frozenset({"sedan", "suv", "luxury", "wav"})


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class TransportPreferenceBase(BaseModel):
    """Shared writable fields used in create and update schemas."""

    preferred_vehicle_type: Optional[str] = Field(
        None,
        max_length=50,
        description="Preferred vehicle category (sedan / suv / luxury / wav)",
    )
    accessibility_needs: Optional[list[str]] = Field(
        None,
        description=(
            "List of accessibility need tags, e.g. "
            "['wheelchair_accessible', 'service_animal']"
        ),
    )
    home_address: Optional[str] = Field(
        None, max_length=255, description="Home street address for commuter rides"
    )
    home_latitude: Optional[float] = Field(
        None, ge=-90.0, le=90.0, description="Latitude of home address"
    )
    home_longitude: Optional[float] = Field(
        None, ge=-180.0, le=180.0, description="Longitude of home address"
    )
    default_cost_center_id: Optional[int] = Field(
        None, description="Default cost centre ID pre-filled on new corporate bookings"
    )
    default_trip_purpose_id: Optional[int] = Field(
        None, description="Default trip purpose ID pre-filled on new corporate bookings"
    )
    preferred_pickup_note: Optional[str] = Field(
        None, description="Driver instructions shown on every corporate booking"
    )
    notify_sms_number: Optional[str] = Field(
        None, max_length=20, description="Phone number for SMS ride-status updates"
    )

    @field_validator("preferred_vehicle_type")
    @classmethod
    def validate_vehicle_type(cls, v: str | None) -> str | None:
        if v is not None and v not in KNOWN_VEHICLE_TYPES:
            raise ValueError(
                f"preferred_vehicle_type must be one of: "
                f"{', '.join(sorted(KNOWN_VEHICLE_TYPES))}"
            )
        return v

    @field_validator("accessibility_needs")
    @classmethod
    def validate_accessibility_needs(
        cls, v: list[str] | None
    ) -> list[str] | None:
        if v is not None:
            unknown = [tag for tag in v if tag not in KNOWN_ACCESSIBILITY_NEEDS]
            if unknown:
                raise ValueError(
                    f"Unknown accessibility need tag(s): {unknown}. "
                    f"Known tags: {sorted(KNOWN_ACCESSIBILITY_NEEDS)}"
                )
        return v


# ---------------------------------------------------------------------------
# Update (all fields optional — partial PUT/PATCH semantics)
# ---------------------------------------------------------------------------


class TransportPreferenceUpdate(TransportPreferenceBase):
    """All fields optional for partial updates."""

    is_active: Optional[bool] = Field(
        None, description="Set to false to disable preferences without deleting them"
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class TransportPreferenceResponse(BaseModel):
    """Full transport preference representation returned to callers."""

    id: int
    account_id: int
    member_id: int
    preferred_vehicle_type: Optional[str]
    accessibility_needs: Optional[list[str]]
    home_address: Optional[str]
    home_latitude: Optional[float]
    home_longitude: Optional[float]
    default_cost_center_id: Optional[int]
    default_trip_purpose_id: Optional[int]
    preferred_pickup_note: Optional[str]
    notify_sms_number: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# List response
# ---------------------------------------------------------------------------


class TransportPreferenceListResponse(BaseModel):
    """List of transport preferences."""

    items: list[TransportPreferenceResponse]
    total: int


# ---------------------------------------------------------------------------
# Booking defaults response
# ---------------------------------------------------------------------------


class BookingDefaultsResponse(BaseModel):
    """Subset of transport preferences used to pre-populate a booking form.

    Returned by the ``apply-to-booking`` endpoint and by the member's
    own preference GET endpoint with ``include_defaults=true``.
    """

    member_id: int
    preferred_vehicle_type: Optional[str]
    accessibility_needs: Optional[list[str]]
    preferred_pickup_note: Optional[str]
    default_cost_center_id: Optional[int]
    default_trip_purpose_id: Optional[int]
    home_address: Optional[str]
    home_latitude: Optional[float]
    home_longitude: Optional[float]
    has_wav_requirement: bool = Field(
        ..., description="True if 'wav' is the preferred vehicle type or 'wheelchair_accessible' is in accessibility_needs"
    )
