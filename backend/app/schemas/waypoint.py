from datetime import datetime

from pydantic import BaseModel, field_validator


class WaypointCreate(BaseModel):
    address: str
    lat: float
    lng: float
    wait_time_minutes: int = 3
    notes: str | None = None

    @field_validator("wait_time_minutes")
    @classmethod
    def validate_wait_time(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("wait_time_minutes must be between 1 and 10")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if v < -90 or v > 90:
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if v < -180 or v > 180:
            raise ValueError("lng must be between -180 and 180")
        return v


class WaypointUpdate(BaseModel):
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    wait_time_minutes: int | None = None
    notes: str | None = None

    @field_validator("wait_time_minutes")
    @classmethod
    def validate_wait_time(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 10):
            raise ValueError("wait_time_minutes must be between 1 and 10")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float | None) -> float | None:
        if v is not None and (v < -90 or v > 90):
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float | None) -> float | None:
        if v is not None and (v < -180 or v > 180):
            raise ValueError("lng must be between -180 and 180")
        return v


class WaypointResponse(BaseModel):
    id: int
    ride_id: int
    order: int
    address: str
    lat: float
    lng: float
    status: str
    wait_time_minutes: int
    notes: str | None = None
    estimated_arrival_at: datetime | None = None
    actual_arrival_at: datetime | None = None
    departed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WaypointListResponse(BaseModel):
    ride_id: int
    waypoints: list[WaypointResponse]
    total_waypoints: int


class MultiStopFareEstimateRequest(BaseModel):
    """Fare estimate for a ride with intermediate stops."""

    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    waypoints: list[WaypointCreate]

    @field_validator("waypoints")
    @classmethod
    def validate_waypoint_count(cls, v: list[WaypointCreate]) -> list[WaypointCreate]:
        if len(v) > 3:
            raise ValueError("Maximum 3 waypoints allowed")
        if len(v) == 0:
            raise ValueError("At least 1 waypoint required for multi-stop estimate")
        return v


class MultiStopFareEstimateResponse(BaseModel):
    total_fare: float
    total_distance_km: float
    total_duration_min: float
    wait_time_minutes: int
    currency: str = "USD"
    legs: list["LegEstimate"]


class LegEstimate(BaseModel):
    from_address: str
    to_address: str
    distance_km: float
    duration_min: float
    fare_contribution: float
