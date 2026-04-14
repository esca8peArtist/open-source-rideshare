"""Pydantic schemas for driver expense tracking endpoints.

Provides:
- ExpenseCreate        — request body for POST /drivers/me/expenses
- ExpenseResponse      — single expense record returned to the client
- CategoryBreakdown    — per-category totals within a summary
- ExpenseSummaryResponse — full summary for GET /drivers/me/expenses/summary
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.driver_expense import ExpenseCategory


class ExpenseCreate(BaseModel):
    """Request body for logging a new driver expense."""

    category: ExpenseCategory = Field(
        ...,
        description=(
            "Expense category. For 'mileage', supply miles driven in the "
            "amount field; for all other categories supply the dollar amount."
        ),
    )
    amount: float = Field(
        ...,
        gt=0,
        description="Dollar amount (or miles for the mileage category).",
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="Optional free-text note about the expense.",
    )
    expense_date: date = Field(
        ...,
        description="Calendar date the expense occurred (YYYY-MM-DD).",
    )
    is_deductible: bool = Field(
        default=True,
        description="Whether this expense is considered tax-deductible.",
    )


class ExpenseResponse(BaseModel):
    """Full representation of a single logged expense."""

    id: int
    driver_id: int
    category: ExpenseCategory
    amount: float
    description: str | None
    expense_date: date
    is_deductible: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryBreakdown(BaseModel):
    """Aggregate totals for a single expense category within a summary period."""

    category: ExpenseCategory
    total_amount: float = Field(..., description="Sum of amounts in this category")
    count: int = Field(..., description="Number of expense records in this category")


class ExpenseSummaryResponse(BaseModel):
    """Response for GET /drivers/me/expenses/summary.

    Per-category subtotals, grand total across all categories, and a
    separate total limited to deductible expenses only.
    """

    period_start: date = Field(..., description="Start of the summary period (inclusive)")
    period_end: date = Field(..., description="End of the summary period (inclusive)")
    categories: list[CategoryBreakdown] = Field(
        ..., description="Breakdown of totals by expense category"
    )
    grand_total: float = Field(
        ..., description="Sum of all expense amounts regardless of deductibility"
    )
    deductible_total: float = Field(
        ..., description="Sum of amounts where is_deductible=True"
    )
