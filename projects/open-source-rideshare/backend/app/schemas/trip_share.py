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
    """Public read-only view — no PII beyond what the rider chose to share."""

    token: str
    ride_id: int
    status: str
    driver_first_name: str
    vehicle_make: str
    vehicle_model: str
    vehicle_color: str
    vehicle_plate: str
    pickup_address: str
    dropoff_address: str
    driver_lat: float | None
    driver_lng: float | None
    eta_minutes: int | None
    expires_at: datetime
