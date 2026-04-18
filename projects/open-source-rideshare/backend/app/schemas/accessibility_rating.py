"""Pydantic schemas for the accessibility rating feature.

Riders rate how well their accessibility needs were accommodated after a
completed ride. These schemas handle:
- AccessibilityRatingCreate: validated input from the rider
- AccessibilityRatingResponse: single rating record returned to the caller
- AccessibilityRatingSummary: admin aggregate stats by accommodation type
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.accessibility_rating import AccommodationType


class AccessibilityRatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Star rating from 1 (worst) to 5 (best)")
    accommodation_type: AccommodationType | None = Field(
        None,
        description="Which accessibility need is being rated (omit for general feedback)",
    )
    comment: str | None = Field(
        None,
        max_length=1000,
        description="Optional free-text note about the accommodation experience",
    )


class AccessibilityRatingResponse(BaseModel):
    id: int
    ride_id: int
    rider_id: int
    rating: int
    accommodation_type: AccommodationType | None
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccommodationTypeStat(BaseModel):
    accommodation_type: AccommodationType | None
    avg_rating: float
    total_ratings: int


class AccessibilityRatingSummary(BaseModel):
    """Admin-facing aggregate quality stats across all accessibility ratings."""

    overall_avg: float
    total_ratings: int
    by_accommodation_type: list[AccommodationTypeStat]
