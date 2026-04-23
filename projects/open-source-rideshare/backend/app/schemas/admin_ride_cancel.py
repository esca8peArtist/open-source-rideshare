"""Schemas for admin ride force-cancel feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdminRideCancelRequest(BaseModel):
    reason: str = Field(default="", description="Admin explanation — stored for audit trail")
    notify_parties: bool = Field(default=True, description="Send RIDE_CANCELLED notifications to rider and driver")


class AdminRideCancelResponse(BaseModel):
    ride_id: int
    previous_status: str
    cancelled_at: datetime
    refund_issued: bool
    rider_notified: bool
    driver_notified: bool
