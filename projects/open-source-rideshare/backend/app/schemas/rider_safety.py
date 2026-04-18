"""Pydantic schemas for rider emergency safety features.

POST   /riders/me/panic
GET    /riders/me/panic/{alert_id}
DELETE /riders/me/panic/{alert_id}
GET    /admin/panic-alerts
POST   /admin/panic-alerts/{alert_id}/resolve

POST   /riders/me/trusted-contacts
GET    /riders/me/trusted-contacts
PUT    /riders/me/trusted-contacts/{contact_id}
DELETE /riders/me/trusted-contacts/{contact_id}
GET    /riders/me/trusted-contacts/{contact_id}/notification-log

Panic button and trusted contact alerts are safety-critical features.
A cooperative platform should give riders tools to protect themselves
and keep people they trust informed during rides.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Panic alert enums and schemas
# ---------------------------------------------------------------------------


class PanicAlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class TriggerPanicRequest(BaseModel):
    """Request body for triggering a panic alert during an active ride."""

    location_lat: Optional[float] = Field(
        None,
        description="Rider's latitude at the time of trigger (optional).",
    )
    location_lng: Optional[float] = Field(
        None,
        description="Rider's longitude at the time of trigger (optional).",
    )


class PanicAlertResponse(BaseModel):
    """Panic alert record returned to rider and admin."""

    id: str = Field(..., description="Unique panic alert identifier (UUID).")
    ride_id: int = Field(..., description="ID of the active ride when alert was triggered.")
    rider_id: int = Field(..., description="ID of the rider who triggered the alert.")
    driver_id: int = Field(..., description="ID of the driver on the active ride.")
    triggered_at: datetime = Field(..., description="UTC timestamp when alert was triggered.")
    location_lat: Optional[float] = Field(None, description="Rider latitude at trigger time.")
    location_lng: Optional[float] = Field(None, description="Rider longitude at trigger time.")
    status: PanicAlertStatus = Field(..., description="Current alert status.")
    resolved_at: Optional[datetime] = Field(None, description="UTC timestamp of resolution.")
    resolved_by: Optional[int] = Field(None, description="Admin user ID who resolved the alert.")
    resolution_notes: Optional[str] = Field(None, description="Admin resolution notes.")

    model_config = {"from_attributes": True}


class AdminResolvePanicRequest(BaseModel):
    """Admin request body for resolving a panic alert."""

    resolution_notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional notes on how the situation was handled.",
    )


class PanicAlertListResponse(BaseModel):
    """Paginated list of active panic alerts (admin view)."""

    total: int = Field(..., description="Total number of ACTIVE panic alerts.")
    items: list[PanicAlertResponse] = Field(..., description="Page of alert records.")


# ---------------------------------------------------------------------------
# Trusted contact enums and schemas
# ---------------------------------------------------------------------------


class TrustedContactNotificationType(str, Enum):
    TRIP_START = "TRIP_START"
    TRIP_END = "TRIP_END"
    PANIC_ALERT = "PANIC_ALERT"


class TrustedContactDeliveryStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class TrustedContactCreate(BaseModel):
    """Request body for adding a trusted contact."""

    name: str = Field(..., min_length=1, max_length=255, description="Contact's full name.")
    phone: str = Field(
        ...,
        min_length=7,
        max_length=20,
        description="Contact's phone number.",
    )
    email: Optional[str] = Field(
        None,
        max_length=255,
        description="Contact's email address (optional).",
    )
    notify_on_trip_start: bool = Field(
        True,
        description="Send notification when rider starts a trip.",
    )
    notify_on_trip_end: bool = Field(
        True,
        description="Send notification when rider's trip ends.",
    )
    notify_on_panic: bool = Field(
        True,
        description="Send notification if rider triggers a panic alert.",
    )


class TrustedContactUpdate(BaseModel):
    """Request body for updating a trusted contact.  All fields optional."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, min_length=7, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    notify_on_trip_start: Optional[bool] = None
    notify_on_trip_end: Optional[bool] = None
    notify_on_panic: Optional[bool] = None


class TrustedContactResponse(BaseModel):
    """Trusted contact record returned to the rider."""

    id: str = Field(..., description="Unique contact identifier (UUID).")
    rider_id: int = Field(..., description="ID of the rider who owns this contact.")
    name: str
    phone: str
    email: Optional[str]
    notify_on_trip_start: bool
    notify_on_trip_end: bool
    notify_on_panic: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TrustedContactNotificationResponse(BaseModel):
    """A notification sent to a trusted contact."""

    id: str = Field(..., description="Unique notification identifier (UUID).")
    contact_id: str = Field(..., description="ID of the trusted contact.")
    ride_id: int = Field(..., description="ID of the ride this notification relates to.")
    notification_type: TrustedContactNotificationType
    sent_at: datetime
    delivery_status: TrustedContactDeliveryStatus
    message_preview: str = Field(..., description="Short preview of the notification message.")

    model_config = {"from_attributes": True}


class TrustedContactNotificationLogResponse(BaseModel):
    """List of recent notifications sent to a trusted contact."""

    contact_id: str
    items: list[TrustedContactNotificationResponse]


# ---------------------------------------------------------------------------
# Safe arrival schemas
# ---------------------------------------------------------------------------


class SafeArrivalCreate(BaseModel):
    """Request body for confirming safe arrival after a completed ride."""

    notes: Optional[str] = Field(
        None,
        description="Optional note from the rider about their arrival.",
    )


class SafeArrivalResponse(BaseModel):
    """Safe arrival confirmation record."""

    id: int = Field(..., description="Unique record identifier.")
    ride_id: int = Field(..., description="ID of the completed ride.")
    user_id: int = Field(..., description="ID of the rider who confirmed arrival.")
    confirmed_at: datetime = Field(
        ..., description="UTC timestamp when arrival was confirmed."
    )
    notes: Optional[str] = Field(None, description="Optional rider note.")

    model_config = {"from_attributes": True}
