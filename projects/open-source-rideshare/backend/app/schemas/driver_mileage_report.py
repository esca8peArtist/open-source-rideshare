"""Schemas for the driver mileage report endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MonthlyMileageBreakdown(BaseModel):
    month: int
    rides_completed: int
    total_km: float
    total_miles: float
    irs_deduction_usd: float


class DriverMileageReport(BaseModel):
    driver_id: int
    year: int
    month: int | None
    as_of: datetime
    rides_completed: int
    total_km: float
    total_miles: float
    irs_rate_per_mile: float
    irs_deduction_usd: float
    monthly_breakdown: list[MonthlyMileageBreakdown]
