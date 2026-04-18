"""Pydantic schemas for the rider spending summary response.

Provides a snapshot of a rider's spending across multiple time windows
(today, this week, this month, lifetime) along with total tips given,
total promo savings, and their most frequently travelled route.

This transparency feature lets riders see exactly how much they have
spent and saved without digging through individual receipts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SpendingPeriod(BaseModel):
    """Aggregated spending for a single time window."""

    trip_count: int
    total_spent: float  # sum of actual_fare for completed rides in the period
    avg_fare: float  # total_spent / trip_count, or 0.0 when trip_count == 0


class FrequentRoute(BaseModel):
    """The pickup → dropoff pair the rider uses most often (lifetime)."""

    pickup: str
    dropoff: str
    count: int


class RiderSpendingSummary(BaseModel):
    """Full spending summary returned by GET /riders/me/spending-summary."""

    rider_id: int
    as_of: datetime  # timestamp the snapshot was computed

    today: SpendingPeriod
    this_week: SpendingPeriod  # Monday 00:00 UTC of current ISO week to now
    this_month: SpendingPeriod  # 1st of current month 00:00 UTC to now
    lifetime: SpendingPeriod  # all completed rides ever

    total_tips_given: float  # sum of tip_amount across all lifetime completed rides
    total_promo_savings: float  # sum of promo_discount across all lifetime completed rides
    most_frequent_route: Optional[FrequentRoute]  # None when the rider has no completed rides
