"""Pydantic schemas for the driver earnings summary response.

Provides a snapshot of a driver's earnings across multiple time windows
(today, this week, this month, lifetime) plus pending payout information.

This is a cooperative transparency feature — drivers can see exactly how
their earnings break down without navigating complex reports.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class EarningsPeriod(BaseModel):
    """Aggregated earnings for a single time window."""

    rides_completed: int
    gross_earnings_usd: float  # sum of actual_fare for the period
    platform_fee_usd: float  # platform's share deducted from gross
    net_earnings_usd: float  # gross_earnings_usd - platform_fee_usd
    tips_usd: float  # sum of tip_amount for the period
    total_take_home_usd: float  # net_earnings_usd + tips_usd


class DriverEarningsSummary(BaseModel):
    """Full earnings summary returned by GET /driver/me/earnings-summary."""

    driver_id: int
    as_of: datetime  # timestamp the snapshot was computed

    today: EarningsPeriod
    this_week: EarningsPeriod  # Monday 00:00 UTC of current ISO week to now
    this_month: EarningsPeriod  # 1st of current month 00:00 UTC to now
    lifetime: EarningsPeriod  # all completed rides ever

    pending_payout_usd: float  # net+tip from rides not yet covered by a COMPLETED payout
    next_payout_date: Optional[date]  # None if no bank account on file
