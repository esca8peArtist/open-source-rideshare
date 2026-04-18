"""Pydantic schemas for the driver ratings history endpoint.

Drivers can view their own rating history submitted by riders, along with
aggregate stats (lifetime average, breakdown per star level, and a recent
trend based on the last 10 ratings).

Rider identity is intentionally excluded from all response shapes to preserve
rider privacy.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DriverRatingItem(BaseModel):
    """A single rating received by a driver from a rider.

    ride_id: the completed ride this rating belongs to.
    rating: integer 1-5 star value.
    comment: optional rider comment, or null when none was left.
    rated_at: ISO 8601 datetime when the rating was submitted.

    Note: rider identity is intentionally omitted to protect rider privacy.
    """

    ride_id: int = Field(..., description="ID of the rated ride")
    rating: int = Field(..., ge=1, le=5, description="Star rating (1–5)")
    comment: str | None = Field(None, description="Optional rider comment")
    rated_at: datetime = Field(..., description="When the rating was submitted")

    model_config = {"from_attributes": True}


class RatingBreakdown(BaseModel):
    """Count of ratings received at each star level."""

    five: int = Field(0, alias="5", description="Number of 5-star ratings")
    four: int = Field(0, alias="4", description="Number of 4-star ratings")
    three: int = Field(0, alias="3", description="Number of 3-star ratings")
    two: int = Field(0, alias="2", description="Number of 2-star ratings")
    one: int = Field(0, alias="1", description="Number of 1-star ratings")

    model_config = {"populate_by_name": True}


class DriverRatingsResponse(BaseModel):
    """Paginated rating history for the authenticated driver.

    average_rating: lifetime average across all completed rides with a rating,
        rounded to 2 decimal places; null if no ratings have been received yet.
    total_ratings: total number of ratings received.
    rating_breakdown: count of ratings at each star level (1–5).
    recent_trend: average of the driver's most recent 10 ratings (or all ratings
        if fewer than 10 exist); null if no ratings yet.
    ratings: paginated list of individual rating records, newest first.
    page / page_size / total_pages: standard pagination metadata.
    """

    average_rating: float | None = Field(
        None,
        description="Lifetime average rating, null if no ratings yet",
    )
    total_ratings: int = Field(..., description="Total number of ratings received")
    rating_breakdown: RatingBreakdown = Field(
        ..., description="Count of ratings at each star level"
    )
    recent_trend: float | None = Field(
        None,
        description="Average of the last 10 ratings; null if no ratings yet",
    )
    ratings: list[DriverRatingItem] = Field(
        ..., description="Paginated list of individual ratings, newest first"
    )
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Number of ratings per page")
    total_pages: int = Field(..., description="Total number of pages")
