"""Pydantic schemas for the rider rating feature.

Drivers rate riders after completing a trip. These schemas handle:
- RiderRatingCreate: validated input from the driver
- RiderRatingResponse: single rating record returned to the caller
- RiderRatingSummary: aggregate stats for a rider's public profile
"""

from datetime import datetime

from pydantic import BaseModel, Field


class RiderRatingCreate(BaseModel):
    """Request body for a driver submitting a rating for a rider.

    ride_id: the completed ride being rated.
    rating: integer 1-5 star value (inclusive).
    comment: optional free-text note from driver to admin (not shown to rider).
    """

    ride_id: int = Field(..., description="ID of the completed ride being rated")
    rating: int = Field(..., ge=1, le=5, description="Star rating from 1 (worst) to 5 (best)")
    comment: str | None = Field(
        None,
        max_length=1000,
        description="Optional driver note (visible to admins only)",
    )


class RiderRatingResponse(BaseModel):
    """Response body for a single rider rating record."""

    id: int
    ride_id: int
    driver_id: int
    rider_id: int
    rating: int
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RatingDistribution(BaseModel):
    """Per-star breakdown of a rider's ratings."""

    one_star: int = 0
    two_star: int = 0
    three_star: int = 0
    four_star: int = 0
    five_star: int = 0


class RiderRatingSummary(BaseModel):
    """Aggregate rating summary for a rider.

    avg_rating: lifetime average rounded to 2 decimal places (5.0 if no ratings yet).
    total_ratings: total number of ratings received.
    rating_distribution: count of ratings at each star level.
    low_rated: True if the rider's 30-day average is below 3.0 with more than 5 ratings.
               This field is only populated for admin callers.
    """

    avg_rating: float
    total_ratings: int
    rating_distribution: RatingDistribution
    low_rated: bool | None = None
