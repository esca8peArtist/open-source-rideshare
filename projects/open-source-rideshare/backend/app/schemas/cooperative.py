"""Schemas for cooperative transparency and member equity endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Public platform stats
# ---------------------------------------------------------------------------

class PlatformPublicStats(BaseModel):
    total_completed_rides: int
    total_cancelled_rides: int
    total_fare_collected_usd: float
    total_platform_fees_usd: float
    total_driver_earnings_usd: float
    total_tips_usd: float
    platform_fee_rate_pct: float = Field(
        description="Percent of total fare retained by the platform"
    )
    driver_take_rate_pct: float = Field(
        description="Percent of total fare paid out to drivers"
    )
    total_approved_drivers: int
    total_active_riders: int
    drivers_currently_online: int


# ---------------------------------------------------------------------------
# Driver equity
# ---------------------------------------------------------------------------

class DriverEquityStats(BaseModel):
    driver_profile_id: int
    driver_name: str | None
    member_since: str | None
    tenure_days: int
    lifetime_completed_trips: int
    platform_total_trips: int
    equity_share_pct: float = Field(
        description="Driver's completed trips as a percent of all platform trips — proxy for cooperative equity share"
    )
    lifetime_earnings_usd: float
    lifetime_tips_usd: float
    lifetime_platform_contribution_usd: float = Field(
        description="Total platform fees generated from this driver's rides"
    )
    rating_avg: float
    is_approved: bool


# ---------------------------------------------------------------------------
# Quarterly transparency report
# ---------------------------------------------------------------------------

class GenerateReportRequest(BaseModel):
    year: int = Field(ge=2020, le=2100)
    quarter: int = Field(ge=1, le=4)
    notes: str | None = None


class CooperativeReportResponse(BaseModel):
    id: int
    year: int
    quarter: int
    total_rides: int
    total_cancelled_rides: int
    total_fare_collected_usd: float
    total_platform_fees_usd: float
    total_driver_earnings_usd: float
    total_tips_usd: float
    platform_fee_rate_pct: float
    driver_take_rate_pct: float
    active_drivers: int
    active_riders: int
    new_drivers: int
    new_riders: int
    generated_at: datetime
    notes: str | None

    model_config = {"from_attributes": True}


class CooperativeReportListResponse(BaseModel):
    reports: list[CooperativeReportResponse]
    total: int
