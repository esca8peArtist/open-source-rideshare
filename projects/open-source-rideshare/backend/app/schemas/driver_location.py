"""Pydantic schemas for driver live location tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.driver_location import DriverLocation


class LocationUpdate(BaseModel):
    """Payload for a driver's GPS location push."""

    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS-84 latitude")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS-84 longitude")
    accuracy_meters: Optional[float] = Field(
        None, ge=0.0, le=10000.0, description="GPS accuracy radius in metres"
    )
    heading: Optional[float] = Field(
        None, ge=0.0, lt=360.0, description="Compass bearing 0–360°"
    )
    speed_kmh: Optional[float] = Field(
        None, ge=0.0, le=300.0, description="Ground speed in km/h"
    )
    # Optional: associate with an active ride
    ride_id: Optional[int] = None

    @field_validator("latitude")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if v == 0.0:
            # Accept 0,0 (valid coordinate, though unusual) but warn callers
            pass
        return round(v, 8)

    @field_validator("longitude")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        return round(v, 8)


class DriverLocationResponse(BaseModel):
    """Current location snapshot for a driver."""

    driver_id: int
    ride_id: Optional[int]
    latitude: float
    longitude: float
    accuracy_meters: Optional[float]
    heading: Optional[float]
    speed_kmh: Optional[float]
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj: DriverLocation) -> "DriverLocationResponse":
        return cls(
            driver_id=obj.driver_id,
            ride_id=obj.ride_id,
            latitude=obj.latitude,
            longitude=obj.longitude,
            accuracy_meters=obj.accuracy_meters,
            heading=obj.heading,
            speed_kmh=obj.speed_kmh,
            is_active=obj.is_active,
            updated_at=obj.updated_at,
        )


class ActiveDriverEntry(BaseModel):
    """One row in the admin live-driver listing."""

    driver_id: int
    driver_name: Optional[str] = None
    ride_id: Optional[int]
    latitude: float
    longitude: float
    accuracy_meters: Optional[float]
    heading: Optional[float]
    speed_kmh: Optional[float]
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActiveDriversResponse(BaseModel):
    """Admin: list of all drivers currently broadcasting location."""

    drivers: list[ActiveDriverEntry]
    total: int
