from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AdminTripShareEntry(BaseModel):
    id: int
    token: str
    share_url: str
    rider_id: int
    ride_id: int
    is_active: bool
    expires_at: datetime
    created_at: datetime


class AdminTripShareListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[AdminTripShareEntry]


class TripShareLinkResponse(BaseModel):
    token: str
    share_url: str
    expires_at: datetime
    is_active: bool
    created_at: datetime


class TripShareView(BaseModel):
    """Public read-only view — no PII beyond what the rider chose to share.

    Driver/vehicle fields are nullable: they are None when the ride has no
    assigned driver yet, or when the ride record cannot be found.
    """

    token: str
    ride_id: int
    status: str
    driver_first_name: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_color: str | None = None
    vehicle_plate: str | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    driver_lat: float | None = None
    driver_lng: float | None = None
    eta_minutes: int | None = None
    expires_at: datetime
