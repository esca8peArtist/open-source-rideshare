"""Schemas for driver in-ride navigation endpoints."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StopType(str, enum.Enum):
    PICKUP = "pickup"
    WAYPOINT = "waypoint"
    DROPOFF = "dropoff"


class StopStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class NavigationStop(BaseModel):
    type: StopType
    index: int
    address: str
    lat: float
    lng: float
    status: StopStatus
    waypoint_id: Optional[int] = None
    wait_time_minutes: Optional[int] = None
    arrived_at: Optional[datetime] = None
    departed_at: Optional[datetime] = None
    distance_km: Optional[float] = None
    eta_minutes: Optional[int] = None

    model_config = {"from_attributes": True}


class NavigationStateResponse(BaseModel):
    ride_id: int
    ride_status: str
    stops: list[NavigationStop]
    next_stop: Optional[NavigationStop] = None
    current_stop_index: Optional[int] = None
    driver_lat: Optional[float] = None
    driver_lng: Optional[float] = None
    route_deviation_flagged: bool
    total_remaining_km: float
    total_remaining_minutes: int


class NavigationPositionUpdate(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Driver latitude")
    lng: float = Field(..., ge=-180.0, le=180.0, description="Driver longitude")
