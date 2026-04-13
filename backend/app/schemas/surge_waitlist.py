"""Pydantic schemas for surge waitlist endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class SurgeWaitlistCreate(BaseModel):
    """Request body for joining the surge waitlist."""

    origin_lat: float = Field(..., ge=-90.0, le=90.0, description="Pickup latitude")
    origin_lon: float = Field(..., ge=-180.0, le=180.0, description="Pickup longitude")

    destination_lat: float | None = Field(None, ge=-90.0, le=90.0)
    destination_lon: float | None = Field(None, ge=-180.0, le=180.0)

    max_multiplier: float = Field(
        1.5,
        ge=1.0,
        le=5.0,
        description="Notify when surge multiplier drops to/below this value.",
    )

    vehicle_preference: str | None = Field(
        None,
        max_length=50,
        description="Optional vehicle service category (e.g. 'standard', 'xl').",
    )

    notify_via_push: bool = True
    notify_via_sms: bool = False

    @model_validator(mode="after")
    def destination_coords_both_or_neither(self) -> "SurgeWaitlistCreate":
        dest_lat = self.destination_lat
        dest_lon = self.destination_lon
        if (dest_lat is None) != (dest_lon is None):
            raise ValueError(
                "destination_lat and destination_lon must both be provided or both omitted"
            )
        return self


class SurgeWaitlistResponse(BaseModel):
    """Surge waitlist entry representation."""

    id: uuid.UUID
    rider_id: int
    origin_lat: float
    origin_lon: float
    destination_lat: float | None = None
    destination_lon: float | None = None
    max_multiplier: float
    vehicle_preference: str | None = None
    status: str
    notify_via_push: bool
    notify_via_sms: bool
    expires_at: datetime
    notified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Computed field — not stored in DB
    is_expired: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_entry(cls, entry) -> "SurgeWaitlistResponse":
        """Build response from a SurgeWaitlistEntry ORM object."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        is_expired = entry.status == "expired" or (
            entry.status == "active" and entry.expires_at < now
        )
        return cls(
            id=entry.id,
            rider_id=entry.rider_id,
            origin_lat=entry.origin_lat,
            origin_lon=entry.origin_lon,
            destination_lat=entry.destination_lat,
            destination_lon=entry.destination_lon,
            max_multiplier=entry.max_multiplier,
            vehicle_preference=entry.vehicle_preference,
            status=entry.status,
            notify_via_push=entry.notify_via_push,
            notify_via_sms=entry.notify_via_sms,
            expires_at=entry.expires_at,
            notified_at=entry.notified_at,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            is_expired=is_expired,
        )


class CurrentSurgeResponse(BaseModel):
    """Current surge information for a given location."""

    multiplier: float
    zone_name: str | None = None
    has_surge: bool


class WaitlistCheckResult(BaseModel):
    """Summary returned by the admin check-and-notify trigger."""

    notified: int
    expired: int
    still_active: int
