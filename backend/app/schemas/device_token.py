"""Pydantic schemas for device token registration."""

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterDeviceTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, description="FCM device token")
    platform: str = Field(..., description="Device platform: ios, android, or web")


class DeviceTokenResponse(BaseModel):
    id: int
    token: str
    platform: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
