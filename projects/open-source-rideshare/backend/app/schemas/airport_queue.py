"""Pydantic schemas for the airport queue management system."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.airport_queue import QueueEntryStatus


# ---------------------------------------------------------------------------
# Airport Zone schemas
# ---------------------------------------------------------------------------


class AirportZoneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    airport_code: str = Field(..., min_length=2, max_length=10)
    terminal: str | None = Field(None, max_length=60)
    address: str | None = Field(None, max_length=255)
    latitude: float | None = None
    longitude: float | None = None
    max_queue_size: int = Field(50, ge=1, le=500)
    ttl_minutes: int = Field(120, ge=10, le=480)


class AirportZoneUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    terminal: str | None = Field(None, max_length=60)
    address: str | None = Field(None, max_length=255)
    latitude: float | None = None
    longitude: float | None = None
    max_queue_size: int | None = Field(None, ge=1, le=500)
    ttl_minutes: int | None = Field(None, ge=10, le=480)
    is_active: bool | None = None


class AirportZoneResponse(BaseModel):
    id: int
    name: str
    airport_code: str
    terminal: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    max_queue_size: int
    ttl_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Live stats (populated by service)
    current_queue_size: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Queue entry schemas
# ---------------------------------------------------------------------------


class JoinQueueRequest(BaseModel):
    """Optional: driver can provide their current location when joining."""

    latitude: float | None = None
    longitude: float | None = None


class QueueEntryResponse(BaseModel):
    id: int
    zone_id: int
    driver_id: int
    status: str
    position: int  # 1-based queue position among waiting entries
    joined_at: datetime
    dispatched_at: datetime | None
    left_at: datetime | None
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class DispatchResponse(BaseModel):
    dispatched_entry_id: int
    driver_id: int
    zone_id: int
    dispatched_at: datetime
    next_in_queue: int | None  # driver_id of next driver, if any


class QueuePositionResponse(BaseModel):
    """Lightweight status check for a driver."""

    zone_id: int
    zone_name: str
    airport_code: str
    status: str
    position: int | None  # None if not waiting
    queue_depth: int  # total waiting in zone
    joined_at: datetime
    expires_at: datetime | None


class AdminQueueView(BaseModel):
    """Full queue state for an admin view of a zone."""

    zone: AirportZoneResponse
    waiting: list[QueueEntryResponse]
    total_dispatched_today: int
    total_expired_today: int
