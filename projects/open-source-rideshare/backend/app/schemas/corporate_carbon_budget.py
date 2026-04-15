"""Pydantic v2 schemas for Corporate Carbon Budget & ESG Reporting.

Corporate accounts set a monthly CO2 budget, track emissions across all
employee rides, and generate ESG reports for sustainability reporting.

Public surface
--------------
CarbonBudgetUpsert        — fields for setting/updating the carbon budget.
CarbonBudgetResponse      — full budget configuration returned by the API.
CarbonSummaryResponse     — current-month carbon summary for an account.
CarbonTrendPoint          — single month data point in a trend series.
CarbonTrendResponse       — ordered list of monthly carbon data points.
EmployeeCarbonItem        — per-employee carbon footprint entry.
EmployeeCarbonBreakdownResponse — admin-only per-employee breakdown.
ESGReportResponse         — platform-admin cross-account ESG summary.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Budget configuration schemas
# ---------------------------------------------------------------------------


class CarbonBudgetUpsert(BaseModel):
    """Payload for setting or updating a corporate carbon budget.

    All fields are optional.  Unset fields are left unchanged on update.
    To remove a budget ceiling, set monthly_budget_co2_kg to null explicitly
    in a PATCH context — supply the field with a None value.

    Attributes:
        monthly_budget_co2_kg: CO2 ceiling in kg/month (null = no cap).
        offset_budget_usd: USD budget reserved for voluntary carbon offsets.
        tracking_enabled: Show carbon data to regular members.
        alert_threshold_pct: Alert trigger level (1–100, default 80).
        notes: Sustainability team notes.
    """

    monthly_budget_co2_kg: Optional[Decimal] = None
    offset_budget_usd: Optional[Decimal] = None
    tracking_enabled: Optional[bool] = None
    alert_threshold_pct: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("monthly_budget_co2_kg")
    @classmethod
    def monthly_budget_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("monthly_budget_co2_kg must be greater than 0")
        return v

    @field_validator("offset_budget_usd")
    @classmethod
    def offset_budget_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError("offset_budget_usd must be >= 0")
        return v

    @field_validator("alert_threshold_pct")
    @classmethod
    def threshold_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 100):
            raise ValueError("alert_threshold_pct must be between 1 and 100")
        return v


class CarbonBudgetResponse(BaseModel):
    """Full carbon budget configuration for an account.

    Returned by GET and PUT /carbon-budget endpoints.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    monthly_budget_co2_kg: Optional[Decimal]
    offset_budget_usd: Optional[Decimal]
    tracking_enabled: bool
    alert_threshold_pct: int
    notes: Optional[str]
    updated_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Carbon summary schemas
# ---------------------------------------------------------------------------


class CarbonSummaryResponse(BaseModel):
    """Current-month carbon footprint summary for a corporate account.

    Returned by GET /carbon-summary.  Derived entirely from ride_carbon_records
    linked to rides on this account — no separate aggregation table is needed.

    Attributes:
        account_id: Corporate account.
        month: Calendar month in "YYYY-MM" format.
        total_rides: Number of completed corporate rides with carbon records.
        total_co2_kg: Total CO2 emitted this month in kilograms.
        green_rides: Rides taken in hybrid or electric vehicles.
        green_ride_pct: Percentage of rides that were green (0–100).
        offset_paid_rides: Rides for which a carbon offset was paid.
        total_offset_paid_usd: Total offset payments in USD.
        monthly_budget_co2_kg: Budget ceiling (null if not configured).
        budget_used_pct: Utilisation % (null if no budget configured).
        alert_triggered: True when budget_used_pct >= alert_threshold_pct.
        tracking_enabled: Whether tracking is active for this account.
    """

    account_id: int
    month: str
    total_rides: int
    total_co2_kg: Decimal
    green_rides: int
    green_ride_pct: Decimal
    offset_paid_rides: int
    total_offset_paid_usd: Decimal
    monthly_budget_co2_kg: Optional[Decimal]
    budget_used_pct: Optional[Decimal]
    alert_triggered: bool
    tracking_enabled: bool


# ---------------------------------------------------------------------------
# Trend schemas
# ---------------------------------------------------------------------------


class CarbonTrendPoint(BaseModel):
    """Single calendar-month data point in a carbon trend series.

    Attributes:
        month: "YYYY-MM" label for this data point.
        rides: Corporate rides with carbon records in this month.
        co2_kg: Total CO2 in kilograms for this month.
        green_rides: Hybrid/electric rides in this month.
        offset_paid_usd: Offset payments made this month in USD.
    """

    month: str
    rides: int
    co2_kg: Decimal
    green_rides: int
    offset_paid_usd: Decimal


class CarbonTrendResponse(BaseModel):
    """Ordered series of monthly carbon data points.

    Points are ordered newest-first (consistent with spend trend).
    """

    account_id: int
    months_requested: int
    data: list[CarbonTrendPoint]


# ---------------------------------------------------------------------------
# Employee breakdown schemas
# ---------------------------------------------------------------------------


class EmployeeCarbonItem(BaseModel):
    """Per-employee carbon footprint for a given period.

    Attributes:
        user_id: ID of the employee (rider_id on the rides table).
        rides: Rides taken by this employee on the corporate account.
        co2_kg: Total CO2 attributed to this employee in kg.
        green_rides: Hybrid/electric rides taken by this employee.
        offset_paid_usd: Offsets paid on this employee's rides in USD.
    """

    user_id: int
    rides: int
    co2_kg: Decimal
    green_rides: int
    offset_paid_usd: Decimal


class EmployeeCarbonBreakdownResponse(BaseModel):
    """Admin-only per-employee carbon breakdown for a billing period.

    Returned by GET /carbon/employees.  Ordered by co2_kg descending (highest
    emitters first — useful for sustainability coaching conversations).
    """

    account_id: int
    period_start: date
    period_end: date
    account_total_co2_kg: Decimal
    account_total_rides: int
    employees: list[EmployeeCarbonItem]


# ---------------------------------------------------------------------------
# Platform ESG report schema
# ---------------------------------------------------------------------------


class ESGMonthPoint(BaseModel):
    """Single month in a platform-wide ESG trend series.

    Attributes:
        month: "YYYY-MM" label.
        total_rides: All corporate rides with carbon records.
        total_co2_kg: Platform-wide corporate CO2 in kg.
        green_rides: Hybrid/electric rides.
        green_ride_pct: % of rides that were green.
        total_offset_paid_usd: Total offset payments in USD.
        active_corporate_accounts: Distinct accounts with rides this month.
    """

    month: str
    total_rides: int
    total_co2_kg: Decimal
    green_rides: int
    green_ride_pct: Decimal
    total_offset_paid_usd: Decimal
    active_corporate_accounts: int


class ESGReportResponse(BaseModel):
    """Platform-admin cross-account ESG summary.

    Returned by GET /admin/corporate/carbon/esg-report.  Aggregates carbon
    data across ALL corporate accounts for platform sustainability reporting.
    """

    months_requested: int
    cumulative_co2_kg: Decimal
    cumulative_green_rides: int
    cumulative_rides: int
    cumulative_offset_paid_usd: Decimal
    overall_green_pct: Decimal
    monthly_trend: list[ESGMonthPoint]
