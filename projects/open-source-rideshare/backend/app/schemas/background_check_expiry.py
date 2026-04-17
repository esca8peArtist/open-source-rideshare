"""Schemas for background check expiry tracking and alert endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class ExpiringBackgroundCheckRow(BaseModel):
    """One row in the admin expiring-background-checks list."""

    check_id: int
    driver_profile_id: int
    expires_at: date
    days_until_expiry: int = Field(
        description="Negative means already expired."
    )
    status: str

    model_config = ConfigDict(from_attributes=True)


class ExpiringBackgroundChecksResponse(BaseModel):
    """Paginated list of background checks expiring within the requested window."""

    items: list[ExpiringBackgroundCheckRow]
    total: int

    model_config = ConfigDict(from_attributes=True)


class BackgroundCheckExpiryScanResponse(BaseModel):
    """Result of a background check expiry scan."""

    alerts_sent: int
    by_type: dict[str, int]
