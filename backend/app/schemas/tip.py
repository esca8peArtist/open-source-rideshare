"""Pydantic schemas for the driver tipping feature."""

from datetime import datetime

from pydantic import BaseModel, Field


class TipRequest(BaseModel):
    """Request body for submitting a tip.

    amount_cents: integer cents — minimum $0.50 (50), maximum $50.00 (5000).
    thank_you_message: optional rider note delivered to the driver.
    """

    amount_cents: int = Field(..., ge=50, le=5000, description="Tip amount in cents (50–5000)")
    thank_you_message: str | None = Field(
        None,
        max_length=500,
        description="Optional message from rider to driver",
    )


class TipResponse(BaseModel):
    """Response body returned after submitting or fetching a tip."""

    id: int
    ride_id: int
    driver_id: int
    amount_cents: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
