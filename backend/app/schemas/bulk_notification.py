"""Schemas for admin bulk notification broadcast feature."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BroadcastTarget(str, enum.Enum):
    ALL = "all"
    RIDERS = "riders"
    DRIVERS = "drivers"


_VALID_CHANNELS = {"push", "sms", "email"}


class BulkNotificationRequest(BaseModel):
    target: BroadcastTarget
    title: str = Field(..., max_length=255, min_length=1)
    body: str = Field(..., max_length=2000, min_length=1)
    channels: list[str] = Field(default_factory=lambda: ["push"])
    notification_type: str = "platform_announcement"

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one channel is required")
        invalid = set(v) - _VALID_CHANNELS
        if invalid:
            raise ValueError(
                f"Invalid channel(s): {sorted(invalid)}. "
                f"Must be a subset of: {sorted(_VALID_CHANNELS)}"
            )
        return v


class BulkNotificationResult(BaseModel):
    broadcast_id: int
    target: BroadcastTarget
    title: str
    recipient_count: int
    sent_count: int
    failed_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BroadcastListItem(BaseModel):
    broadcast_id: int
    target: BroadcastTarget
    title: str
    recipient_count: int
    sent_count: int
    failed_count: int
    admin_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
