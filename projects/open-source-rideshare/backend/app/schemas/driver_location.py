"""Pydantic schemas for driver live location endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class LocationUpdateRequest(BaseModel):
    """Body for driver location update."""

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude (-90 to 90)")
    lng: float = Field(..., ge=-180.0, le=180.0, description="Longitude (-180 to 180)")


# ---------------------------------------------------------------------------
# Driver self-view
# ---------------------------------------------------------------------------


class DriverLocationResponse(BaseModel):
    """Driver's own current stored location."""

    lat: float | None = Field(None, description="Latitude, or null if never set")
    lng: float | None = Field(None, description="Longitude, or null if never set")
    updated_at: datetime | None = Field(
        None, description="When the profile was last updated (proxy for last location update)"
    )


# ---------------------------------------------------------------------------
# Rider view — privacy-safe nearby drivers
# ---------------------------------------------------------------------------


class NearbyDriverItem(BaseModel):
    """One nearby available driver with a fuzzed position (privacy-safe).

    Coordinates are rounded to 3 decimal places (~110 m precision) so exact
    driver positions are not exposed to riders.  No driver ID or PII is
    included.
    """

    lat: float = Field(..., description="Fuzzy latitude (±~55 m)")
    lng: float = Field(..., description="Fuzzy longitude (±~55 m at equator)")
    distance_m: float = Field(..., ge=0, description="Approximate distance from query point in metres")


class NearbyDriversResponse(BaseModel):
    """Rider-facing response listing nearby available drivers."""

    drivers: list[NearbyDriverItem]
    total: int = Field(..., ge=0, description="Number of nearby available drivers returned")
    as_of: datetime = Field(..., description="UTC timestamp when the snapshot was taken")


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------


class AdminDriverLocationItem(BaseModel):
    """Exact driver location for admin monitoring."""

    driver_id: int
    lat: float | None
    lng: float | None
    is_online: bool
    is_on_break: bool
    updated_at: datetime | None = Field(
        None, description="When the profile was last updated"
    )


class AdminDriverLocationsResponse(BaseModel):
    """Admin view of all online drivers with exact positions."""

    drivers: list[AdminDriverLocationItem]
    total: int = Field(..., ge=0)
    as_of: datetime


# ---------------------------------------------------------------------------
# Rider-tracking view — assigned driver during an active ride
# ---------------------------------------------------------------------------


class AssignedDriverLocationResponse(BaseModel):
    """Rider's view of their assigned driver's position during an active ride.

    Returned by GET /rides/{ride_id}/driver-location.  The rider sees exact
    coordinates (no fuzzing) for their own assigned driver — this is the live
    tracking map used during MATCHED / DRIVER_EN_ROUTE / ARRIVED phases.

    lat/lng are null when the driver hasn't pushed a location yet.
    distance_to_pickup_m is null when coordinates are unavailable or the ride
    is outside a trackable status.
    """

    ride_status: str = Field(..., description="Current ride status")
    lat: float | None = Field(None, description="Driver's last-known latitude")
    lng: float | None = Field(None, description="Driver's last-known longitude")
    updated_at: datetime | None = Field(None, description="When the driver last updated their position")
    distance_to_pickup_m: float | None = Field(
        None, ge=0, description="Haversine distance from driver to pickup point in metres"
    )
