"""Pydantic schemas for the Corporate Cost Center feature."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CorporateCostCenterCreate(BaseModel):
    """Payload for creating a new cost centre."""

    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Short alphanumeric identifier, unique within the account.",
    )
    description: str | None = Field(None, max_length=300)
    monthly_budget: Decimal | None = Field(
        None,
        gt=0,
        description="Optional monthly spend cap in USD. Must be > 0 if provided.",
    )

    @field_validator("code")
    @classmethod
    def code_alphanumeric(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "code must contain only letters, digits, hyphens, or underscores."
            )
        return cleaned


class CorporateCostCenterUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=300)
    monthly_budget: Decimal | None = Field(None, gt=0)
    is_active: bool | None = None


class CorporateCostCenterResponse(BaseModel):
    """Serialised cost centre returned by the API."""

    id: int
    account_id: int
    name: str
    code: str
    description: str | None
    is_active: bool
    monthly_budget: Decimal | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CostCenterSpendSummary(BaseModel):
    """Per-cost-centre spend report."""

    cost_center_id: int
    cost_center_name: str
    cost_center_code: str
    period_start: str | None  # "YYYY-MM-DD" or None for all-time
    period_end: str | None
    total_rides: int
    total_spend: Decimal
    monthly_budget: Decimal | None
    budget_utilization_pct: float | None  # NULL when no budget set
