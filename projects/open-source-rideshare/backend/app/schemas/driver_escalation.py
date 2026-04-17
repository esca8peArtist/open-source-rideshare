"""Pydantic schemas for the driver accountability escalation feature.

Provides:
- DriverEscalationStatusResponse  — escalation state for a driver (driver or admin view)
- AdminResetEscalationRequest     — admin request body for resetting escalation
- AdminResetEscalationResponse    — result of a reset operation
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DriverEscalationStatusResponse(BaseModel):
    """Escalation state returned to the driver (self-view) or admin."""

    driver_id: int
    escalation_level: str = Field(
        ...,
        description="Current escalation level: none | warning | final_warning | suspended",
    )
    warning_count: int = Field(
        ..., description="Number of escalation-triggering alerts in the current streak"
    )
    last_trigger_type: str | None = Field(
        None, description="Alert type that most recently triggered an escalation"
    )
    last_warning_at: datetime | None = Field(
        None, description="Timestamp of the most recent warning or escalation event"
    )
    auto_suspended_at: datetime | None = Field(
        None, description="Timestamp when the driver was auto-suspended (None if not suspended)"
    )
    last_reset_at: datetime | None = Field(
        None, description="Timestamp when an admin last reset the escalation"
    )

    model_config = ConfigDict(from_attributes=True)


class AdminResetEscalationRequest(BaseModel):
    """Request body for admin escalation reset."""

    note: str | None = Field(
        None,
        max_length=500,
        description="Optional admin note describing the reason for the reset (e.g. coaching completed)",
    )


class AdminResetEscalationResponse(BaseModel):
    """Returned after an admin successfully resets a driver's escalation."""

    driver_id: int
    escalation_level: str
    warning_count: int
    last_reset_at: datetime | None
    admin_reset_note: str | None
    message: str

    model_config = ConfigDict(from_attributes=True)
