"""Pydantic schemas for driver emergency safety features.

POST   /drivers/me/panic
GET    /drivers/me/panic/{alert_id}
DELETE /drivers/me/panic/{alert_id}
GET    /admin/driver-panic-alerts
POST   /admin/driver-panic-alerts/{alert_id}/resolve

Drivers need safety tools just as riders do.  A driver in a threatening
situation should be able to summon help instantly.  Panic alerts are
immediately visible to platform admins sorted oldest-first (most urgent).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DriverPanicAlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class TriggerDriverPanicRequest(BaseModel):
    """Request body for triggering a driver panic alert during an active ride."""

    location_lat: Optional[float] = Field(
        None,
        description="Driver's latitude at the time of trigger (optional).",
    )
    location_lng: Optional[float] = Field(
        None,
        description="Driver's longitude at the time of trigger (optional).",
    )


class DriverPanicAlertResponse(BaseModel):
    """Driver panic alert record returned to driver and admin."""

    id: str = Field(..., description="Unique panic alert identifier (UUID).")
    ride_id: int = Field(..., description="ID of the active ride when alert was triggered.")
    driver_id: int = Field(..., description="ID of the driver who triggered the alert.")
    rider_id: int = Field(..., description="ID of the rider on the active ride.")
    triggered_at: datetime = Field(..., description="UTC timestamp when alert was triggered.")
    location_lat: Optional[float] = Field(None, description="Driver latitude at trigger time.")
    location_lng: Optional[float] = Field(None, description="Driver longitude at trigger time.")
    status: DriverPanicAlertStatus = Field(..., description="Current alert status.")
    resolved_at: Optional[datetime] = Field(None, description="UTC timestamp of resolution.")
    resolved_by: Optional[int] = Field(None, description="Admin user ID who resolved the alert.")
    resolution_notes: Optional[str] = Field(None, description="Admin resolution notes.")

    model_config = {"from_attributes": True}


class AdminResolveDriverPanicRequest(BaseModel):
    """Admin request body for resolving a driver panic alert."""

    resolution_notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional notes on how the situation was handled.",
    )


class DriverPanicAlertListResponse(BaseModel):
    """Paginated list of active driver panic alerts (admin view)."""

    total: int = Field(..., description="Total number of ACTIVE driver panic alerts.")
    items: list[DriverPanicAlertResponse] = Field(..., description="Page of alert records.")
