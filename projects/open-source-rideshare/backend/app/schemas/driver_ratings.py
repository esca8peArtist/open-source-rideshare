"""Pydantic schemas for the driver ratings feature.

Riders rate drivers after completing a trip. These schemas handle:
- DriverRatingDistribution: per-star breakdown
- DriverRatingSummary: aggregate stats for a driver's public profile
- RideDriverRatingResponse: a single ride's driver-rating value
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DriverRatingDistribution(BaseModel):
    """Per-star breakdown of a driver's ratings."""

    one_star: int = 0
    two_star: int = 0
    three_star: int = 0
    four_star: int = 0
    five_star: int = 0


class DriverRatingSummary(BaseModel):
    """Aggregate rating summary for a driver.

    avg_rating: lifetime average rounded to 2 decimal places (5.0 if no ratings yet).
    total_ratings: total number of ratings received.
    rating_distribution: count of ratings at each star level.
    recent_avg: average of the last 20 rated rides; None if fewer than 5 rated rides.
    recent_count: number of rides counted in the recent average.
    low_rated: True if the driver's 30-day average is below 3.0 with more than 5 ratings.
               This field is only populated for admin callers.
    """

    driver_id: int
    avg_rating: float
    total_ratings: int
    rating_distribution: DriverRatingDistribution
    recent_avg: float | None = None
    recent_count: int = 0
    low_rated: bool | None = None


class RideDriverRatingResponse(BaseModel):
    """The driver rating a rider submitted for a specific completed ride."""

    ride_id: int
    driver_id: int
    rider_id: int
    rating: int = Field(..., ge=1, le=5)
    rated_at: datetime | None = None
