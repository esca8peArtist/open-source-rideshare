"""Schemas for surge price lock endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SurgePriceLockRequest(BaseModel):
    """Body for creating a surge price lock."""

    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lon: float = Field(..., ge=-180, le=180)
    pickup_address: str | None = Field(None, max_length=500)


class SurgePriceLockResponse(BaseModel):
    """Response returned after creating or fetching an active lock."""

    id: int
    rider_id: int
    pickup_lat: float
    pickup_lon: float
    pickup_address: str | None

    locked_multiplier: float
    """The surge multiplier captured at lock creation time."""

    locked_at: datetime
    expires_at: datetime
    seconds_remaining: int
    """Seconds until the lock expires.  0 when expired (though active locks
    will never be returned once expired)."""

    is_active: bool
    """True when the lock has not been used, cancelled, or expired."""

    used_at: datetime | None = None
    cancelled_at: datetime | None = None

    model_config = {"from_attributes": True}


class SurgePriceLockCancelResponse(BaseModel):
    """Returned by DELETE /riders/me/surge-lock."""

    cancelled: bool
    message: str
