"""Pydantic schemas for the per-user notification preference feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

# Valid values — kept in sync with NotificationType and NotificationChannel enums.
# Importing the enums directly would create a circular import through the service
# layer, so we maintain the allowed sets here explicitly.
_VALID_NOTIFICATION_TYPES: frozenset[str] = frozenset(
    {
        "ride_matched",
        "ride_cancelled",
        "ride_completed",
        "driver_en_route",
        "driver_arrived",
        "payment_received",
        "sos_alert",
        "rating_received",
        "account_verification",
        "payout_completed",
        "ride_reminder",
        "fare_split_request",
        "promo_applied",
        "background_check_approved",
        "background_check_action_required",
    }
)

_VALID_CHANNELS: frozenset[str] = frozenset({"push", "sms", "email"})


class NotificationPreferenceResponse(BaseModel):
    """Response schema for a single preference record."""

    id: int
    notification_type: str
    channel: str
    enabled: bool

    model_config = {"from_attributes": True}


class SetPreferenceRequest(BaseModel):
    """Request body for setting a single notification preference."""

    notification_type: str
    channel: str
    enabled: bool

    @field_validator("notification_type")
    @classmethod
    def validate_notification_type(cls, v: str) -> str:
        if v not in _VALID_NOTIFICATION_TYPES:
            raise ValueError(
                f"Invalid notification_type '{v}'. "
                f"Valid values: {sorted(_VALID_NOTIFICATION_TYPES)}"
            )
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in _VALID_CHANNELS:
            raise ValueError(
                f"Invalid channel '{v}'. Valid values: {sorted(_VALID_CHANNELS)}"
            )
        return v


class BulkSetPreferenceRequest(BaseModel):
    """Request body for setting multiple preferences in one call."""

    updates: list[SetPreferenceRequest]


class UserPreferencesResponse(BaseModel):
    """Full preference map for a user.

    Structure: {notification_type: {channel: enabled}}
    All type/channel combinations are included; missing DB records are
    represented as enabled=True (the default opt-in state).
    """

    preferences: dict[str, dict[str, bool]]
