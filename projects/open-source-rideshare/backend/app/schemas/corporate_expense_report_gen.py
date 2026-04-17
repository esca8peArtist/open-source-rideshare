"""Pydantic schemas for corporate expense report generation.

These schemas support period-based expense aggregation for members and admins.
They are distinct from the individual expense-submission schemas in
``corporate_expense_report.py``.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class RideLineItem(BaseModel):
    """A single ride included in a member expense report.

    Attributes:
        ride_id: Platform ride identifier.
        date: Date the ride was completed (UTC).
        amount_usd: Fare charged for the ride.
        purpose: Optional trip notes or purpose label attached to the ride.
        status: Ride status at time of report generation.
    """

    ride_id: int
    date: date
    amount_usd: Decimal
    purpose: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class MemberExpenseReport(BaseModel):
    """Expense report aggregated for a single corporate member over a period.

    Attributes:
        member_id: Platform user identifier for the member.
        period_label: Human-readable period string (e.g. "2026-04" or "2026").
        total_rides: Number of corporate rides completed in the period.
        total_amount_usd: Sum of all ride fares in the period.
        avg_per_ride_usd: Average fare per ride (0 when no rides).
        rides: Line-item detail for each ride in the period.
    """

    member_id: int
    period_label: str
    total_rides: int
    total_amount_usd: Decimal
    avg_per_ride_usd: Decimal
    rides: List[RideLineItem] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DeptExpenseSummary(BaseModel):
    """Expense totals for a single department within an account.

    Attributes:
        department_name: Display name of the department.
        total_rides: Number of rides attributed to members of this department.
        total_amount_usd: Sum of fares for those rides.
    """

    department_name: str
    total_rides: int
    total_amount_usd: Decimal

    model_config = {"from_attributes": True}


class MemberExpenseSummary(BaseModel):
    """Expense totals for a single member within an account-level report.

    Attributes:
        member_id: Platform user identifier.
        display_name: User's display name at report time.
        total_rides: Number of rides completed by this member in the period.
        total_amount_usd: Sum of fares for those rides.
    """

    member_id: int
    display_name: str
    total_rides: int
    total_amount_usd: Decimal

    model_config = {"from_attributes": True}


class AccountExpenseReport(BaseModel):
    """Expense report aggregated across an entire corporate account for a period.

    Attributes:
        account_id: Corporate account identifier.
        period_label: Human-readable period string (e.g. "2026-04" or "2026").
        total_rides: Total rides billed to the account in the period.
        total_amount_usd: Total fares billed to the account in the period.
        by_department: Per-department breakdown.
        by_member: Per-member breakdown.
    """

    account_id: int
    period_label: str
    total_rides: int
    total_amount_usd: Decimal
    by_department: List[DeptExpenseSummary] = Field(default_factory=list)
    by_member: List[MemberExpenseSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}
