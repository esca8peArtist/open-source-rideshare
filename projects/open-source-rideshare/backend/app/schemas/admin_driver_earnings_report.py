"""Pydantic schemas for the admin driver earnings report.

Provides platform-wide earnings aggregated per driver for a date range.
Designed for cooperative transparency — admins can see how all drivers'
earnings break down, unlike the top-earners endpoint which shows only top N.
"""

from __future__ import annotations

from pydantic import BaseModel


class PlatformTotals(BaseModel):
    """Sum of earnings figures across all drivers in the report period."""

    total_rides: int
    gross_earnings_usd: float
    platform_fees_usd: float
    net_earnings_usd: float
    tips_usd: float


class DriverEarningsRow(BaseModel):
    """Per-driver earnings breakdown for the report period."""

    driver_id: int
    driver_name: str
    driver_phone: str
    rides_completed: int
    gross_earnings_usd: float
    platform_fee_usd: float
    net_earnings_usd: float
    tips_usd: float
    total_take_home_usd: float
    pending_payout_usd: float


class AdminDriverEarningsReport(BaseModel):
    """Full paginated driver earnings report response.

    Returned by GET /api/v1/admin/drivers/earnings-report.
    """

    period_start: str
    period_end: str
    total_active_drivers: int
    platform_totals: PlatformTotals
    drivers: list[DriverEarningsRow]
    page: int
    page_size: int
    total_count: int
