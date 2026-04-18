"""Pydantic schemas for GET /riders/{rider_id}/public-profile.

Returns non-PII, driver-relevant rider data for the pre-acceptance step.

Deliberately excluded: name, email, phone, referral info, and all PII.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RiderPublicProfile(BaseModel):
    """Public-facing rider profile shown to drivers before accepting a ride."""

    rider_id: int = Field(..., description="Opaque User primary key for this rider")
    rating_avg: float | None = Field(
        None,
        ge=1.0,
        le=5.0,
        description="Average rating submitted by drivers (1–5), null if no ratings yet",
    )
    total_completed_rides: int = Field(
        ..., ge=0, description="Total completed rides as a rider"
    )
    member_since: datetime = Field(..., description="When the rider joined the platform")
