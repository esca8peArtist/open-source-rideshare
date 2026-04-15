"""Pydantic schemas for the driver rating appeal system."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_rating_appeal import AppealStatus


class AppealSubmitRequest(BaseModel):
    """Payload for a driver submitting a rating appeal."""
    feedback_id: int = Field(..., description="ID of the RideFeedback record being appealed")
    reason: str = Field(..., min_length=20, max_length=2000, description="Driver's explanation")


class AppealReviewRequest(BaseModel):
    """Payload for an admin reviewing (approving or rejecting) an appeal."""
    decision: AppealStatus = Field(
        ...,
        description="approved — nullifies rating; rejected — rating stands",
    )
    admin_notes: str = Field(..., min_length=1, max_length=2000)


class AppealResponse(BaseModel):
    """Full appeal record returned to driver or admin."""
    id: int
    driver_id: int
    feedback_id: int
    reason: str
    status: AppealStatus
    admin_notes: str | None
    reviewed_by: int | None
    rating_nullified: bool
    created_at: datetime
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


class AppealSummaryResponse(BaseModel):
    """Aggregate stats for the admin appeal dashboard."""
    total: int
    pending: int
    approved: int
    rejected: int
    nullified: int
