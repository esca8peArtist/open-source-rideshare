"""Pydantic schemas for the rider-submits-driver-rating feature.

Riders rate their driver after a completed ride. One rating per ride per rider.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DriverRatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Star rating from 1 (worst) to 5 (best)")
    comment: str | None = Field(None, max_length=1000, description="Optional feedback from rider")


class DriverRatingResponse(BaseModel):
    id: int
    ride_id: int
    rider_id: int
    rating: int
    comment: str | None
    submitted_at: datetime

    model_config = {"from_attributes": True}
