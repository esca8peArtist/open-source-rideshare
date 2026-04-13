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


class TipStatusBreakdown(BaseModel):
    """Tip count grouped by status."""

    completed: int = 0
    pending: int = 0
    failed: int = 0
    refunded: int = 0


class TipSummaryResponse(BaseModel):
    """Driver's personal tip earnings summary for a given period."""

    period: str
    total_cents: int
    total_dollars: float
    tip_count: int
    avg_tip_cents: int
    avg_tip_dollars: float
    status_breakdown: TipStatusBreakdown


class TopTippedDriver(BaseModel):
    """One entry in the admin top-tipped-drivers list."""

    driver_id: int
    tip_count: int
    total_cents: int
    total_dollars: float


class AdminTipStatsResponse(BaseModel):
    """Platform-wide tip analytics for a given period."""

    period: str
    total_cents: int
    total_dollars: float
    tip_count: int
    avg_tip_cents: int
    avg_tip_dollars: float
    unique_drivers_tipped: int
    unique_riders_who_tipped: int
    top_tipped_drivers: list[TopTippedDriver]
