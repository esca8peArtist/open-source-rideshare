"""Schemas for driver wait time billing."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WaitTimeStatusResponse(BaseModel):
    """Live wait time status for a ride that is in ARRIVED state."""

    ride_id: int
    driver_arrived_at: datetime

    elapsed_seconds: int
    """Total seconds since driver arrived at pickup location."""

    elapsed_minutes: float
    """Convenience: elapsed_seconds / 60."""

    grace_seconds_remaining: int
    """Free waiting seconds remaining before billing starts (0 when grace is over)."""

    billable_minutes: float
    """Minutes beyond the grace period, billed to the rider."""

    accrued_fee: float
    """Current wait time fee owed by the rider (USD)."""

    wait_rate_per_min: float
    """Per-minute rate in effect after the grace period."""

    grace_seconds: int
    """Total grace period length in seconds."""

    max_wait_minutes: int
    """Minutes after which the ride qualifies as a no-show."""

    is_no_show: bool
    """True when the driver has been waiting >= max_wait_minutes."""
