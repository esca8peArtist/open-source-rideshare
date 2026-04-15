"""Pydantic schemas for Corporate Expense Reports."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ExpenseReportCreate(BaseModel):
    """Payload for submitting an expense report."""

    amount_usd: Decimal = Field(
        ...,
        gt=0,
        description="Claimed reimbursement amount in USD.  Must be greater than zero.",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="What the expense was for.",
    )
    ride_id: Optional[int] = Field(
        None,
        description="Optional platform ride linked to this expense.",
    )
    cost_center_id: Optional[int] = Field(
        None,
        description="Optional cost center to tag this expense.",
    )
    trip_purpose_id: Optional[int] = Field(
        None,
        description="Optional trip purpose to tag this expense.",
    )
    receipt_url: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional URL of an attached receipt.",
    )


class ExpenseReportReview(BaseModel):
    """Admin payload for approving or rejecting an expense report."""

    action: Literal["approved", "rejected"] = Field(
        ...,
        description="Decision: 'approved' or 'rejected'.",
    )
    review_note: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional feedback for the employee.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ExpenseReportResponse(BaseModel):
    """Full representation of an expense report."""

    id: int
    account_id: int
    submitted_by_id: int
    ride_id: Optional[int]
    amount_usd: Decimal
    description: str
    cost_center_id: Optional[int]
    trip_purpose_id: Optional[int]
    receipt_url: Optional[str]
    status: str
    reviewed_by_id: Optional[int]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    submitted_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ExpenseReportListResponse(BaseModel):
    """Paginated list of expense reports."""

    account_id: int
    total: int
    reports: list[ExpenseReportResponse]
