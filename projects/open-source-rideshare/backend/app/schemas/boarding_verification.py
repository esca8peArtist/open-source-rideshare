from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PIN
# ---------------------------------------------------------------------------


class GeneratePinRequest(BaseModel):
    """Empty body — ride_id comes from the path."""
    pass


class BoardingPinResponse(BaseModel):
    ride_id: int
    pin: str
    generated_at: datetime
    expires_at: datetime
    expired: bool = False


# ---------------------------------------------------------------------------
# Verification (rider confirmation)
# ---------------------------------------------------------------------------


class ConfirmBoardingRequest(BaseModel):
    pin_entered: str = Field(..., min_length=1, max_length=10, description="PIN received verbally from driver")
    confirmed_driver_name: Optional[str] = Field(None, max_length=100, description="Driver name as shown on door — rider confirms it matches")
    confirmed_plate: Optional[str] = Field(None, max_length=20, description="License plate — rider confirms it matches")
    notes: Optional[str] = Field(None, max_length=500)


class BoardingVerificationResponse(BaseModel):
    id: int
    ride_id: int
    rider_id: int
    driver_id: Optional[int]
    pin_match: bool
    confirmed: bool
    confirmed_driver_name: Optional[str]
    confirmed_plate: Optional[str]
    notes: Optional[str]
    verified_at: datetime
    alert_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Admin — mismatch alerts
# ---------------------------------------------------------------------------


class MismatchAlertResponse(BaseModel):
    id: int
    ride_id: int
    rider_id: int
    driver_id: Optional[int]
    reason: str
    created_at: datetime
    resolved: bool
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None


class MismatchAlertListResponse(BaseModel):
    alerts: list[MismatchAlertResponse]
    total: int


class ResolveMismatchAlertRequest(BaseModel):
    resolution_notes: Optional[str] = Field(None, max_length=500)
