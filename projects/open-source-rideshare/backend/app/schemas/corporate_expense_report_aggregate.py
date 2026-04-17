"""Pydantic schemas for Corporate Expense Report Aggregates.

These schemas serve the aggregated expense-report generation feature, which
is distinct from the individual expense-submission workflow.  Here an admin
generates a structured report summarising all rides billed to a corporate
account within a date range, grouped by member and category.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-schemas used inside report detail
# ---------------------------------------------------------------------------


class MemberExpenseSummary(BaseModel):
    """Aggregated ride spend for a single corporate account member."""

    member_user_id: int
    member_name: str
    ride_count: int
    total_amount_usd: Decimal

    model_config = {"from_attributes": True}


class CategoryExpenseSummary(BaseModel):
    """Aggregated spend broken down by ride category / vehicle type."""

    category: str
    ride_count: int
    total_amount_usd: Decimal

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ExpenseReportGenerateRequest(BaseModel):
    """Payload for generating a new aggregated expense report."""

    start_date: date = Field(
        ...,
        description="Inclusive start date of the reporting period (YYYY-MM-DD).",
    )
    end_date: date = Field(
        ...,
        description="Inclusive end date of the reporting period (YYYY-MM-DD).",
    )
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional human-readable title for the report.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class GeneratedExpenseReportResponse(BaseModel):
    """Summary view of a generated expense report (used in list endpoints)."""

    id: int
    corp_id: int
    title: str
    start_date: date
    end_date: date
    total_rides: int
    total_amount_usd: Decimal
    generated_at: datetime
    generated_by_id: int

    model_config = {"from_attributes": True}


class GeneratedExpenseReportDetail(BaseModel):
    """Full detail view of a generated expense report, including breakdowns."""

    id: int
    corp_id: int
    title: str
    start_date: date
    end_date: date
    total_rides: int
    total_amount_usd: Decimal
    generated_at: datetime
    generated_by_id: int
    by_member: list[MemberExpenseSummary]
    by_category: list[CategoryExpenseSummary]

    model_config = {"from_attributes": True}


class GeneratedExpenseReportListResponse(BaseModel):
    """Paginated list of generated expense reports."""

    corp_id: int
    total: int
    reports: list[GeneratedExpenseReportResponse]
