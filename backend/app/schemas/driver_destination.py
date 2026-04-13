"""Pydantic schemas for driver destination filter endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class DriverDestinationFilterSet(BaseModel):
    """Request body for setting or updating the destination filter."""

    destination_lat: float = Field(..., ge=-90.0, le=90.0, description="Destination latitude")
    destination_lon: float = Field(..., ge=-180.0, le=180.0, description="Destination longitude")

    radius_km: float = Field(
        5.0,
        ge=1.0,
        le=50.0,
        description="Dropoff must be within this many km of the destination (1–50).",
    )

    expires_at: datetime | None = Field(
        None,
        description="Optional UTC datetime after which the filter auto-expires. "
        "Omit for no expiry.",
    )


class DriverDestinationFilterResponse(BaseModel):
    """Destination filter representation returned to the driver."""

    id: int
    driver_id: int
    destination_lat: float
    destination_lon: float
    radius_km: float
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Computed — True when is_active and not past expires_at
    is_currently_active: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_filter(cls, f) -> "DriverDestinationFilterResponse":
        """Build response from a DriverDestinationFilter ORM object."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        active = f.is_active and (
            f.expires_at is None or f.expires_at > now
        )
        return cls(
            id=f.id,
            driver_id=f.driver_id,
            destination_lat=f.destination_lat,
            destination_lon=f.destination_lon,
            radius_km=f.radius_km,
            is_active=f.is_active,
            expires_at=f.expires_at,
            created_at=f.created_at,
            updated_at=f.updated_at,
            is_currently_active=active,
        )
