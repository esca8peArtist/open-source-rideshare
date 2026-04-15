"""Pydantic v2 schemas for the Corporate Employee Spend Limits feature.

Employees can view their own current-month spend vs their personal monthly
limit.  Corporate admins can set, adjust, or remove per-employee limits and
view a summary across all members.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SetSpendLimitRequest(BaseModel):
    """Payload for setting or updating an employee's monthly spend limit."""

    monthly_limit_usd: Decimal = Field(
        ...,
        gt=0,
        description="Monthly spend cap in USD.  Must be a positive value.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class MySpendSummaryResponse(BaseModel):
    """Current-month and year-to-date spend for the authenticated employee.

    Returned by GET /corporate/accounts/me/my-spending.
    """

    account_id: int
    user_id: int
    current_month: str = Field(
        ..., description="Calendar month in YYYY-MM format."
    )

    # Current-month figures
    current_month_rides: int
    current_month_spend: Decimal

    # Personal limit
    monthly_spend_limit: Optional[Decimal] = Field(
        None, description="Personal monthly cap set by the account admin.  NULL means no cap."
    )
    limit_utilization_pct: Optional[float] = Field(
        None,
        description=(
            "current_month_spend / monthly_spend_limit × 100, rounded to 2 d.p.  "
            "NULL when no limit is set."
        ),
    )

    # Year-to-date
    ytd_rides: int
    ytd_spend: Decimal


class MySpendHistoryPoint(BaseModel):
    """One month of spend data for an individual employee."""

    month: str = Field(..., description="YYYY-MM.")
    total_rides: int
    total_spend: Decimal
    avg_fare: Optional[Decimal]


class MySpendHistoryResponse(BaseModel):
    """Monthly spend history for the authenticated employee."""

    account_id: int
    user_id: int
    months_requested: int
    data: list[MySpendHistoryPoint]


class MemberSpendItem(BaseModel):
    """One row in the admin member-spend-limits overview."""

    user_id: int
    monthly_spend_limit: Optional[Decimal]
    current_month_rides: int
    current_month_spend: Decimal
    limit_utilization_pct: Optional[float]
    is_active: bool


class MemberSpendLimitsResponse(BaseModel):
    """Admin overview of all members with their limits and current usage."""

    account_id: int
    current_month: str
    members: list[MemberSpendItem]


class MemberSpendSummaryResponse(BaseModel):
    """Admin view of a single member's spend summary."""

    account_id: int
    user_id: int
    current_month: str
    current_month_rides: int
    current_month_spend: Decimal
    monthly_spend_limit: Optional[Decimal]
    limit_utilization_pct: Optional[float]
    ytd_rides: int
    ytd_spend: Decimal
    is_active: bool


class SpendLimitResponse(BaseModel):
    """Returned after setting or removing a spend limit."""

    account_id: int
    user_id: int
    monthly_spend_limit: Optional[Decimal]
    message: str
