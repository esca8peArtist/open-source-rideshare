"""Pydantic v2 schemas for the Corporate Budget Alerts feature.

Admins configure percentage-based thresholds on cost centers or the overall
account.  When spend crosses the threshold, an alert is triggered and surfaced
via the API.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class BudgetAlertCreate(BaseModel):
    """Payload for creating a new budget alert threshold."""

    scope: str = Field(
        ...,
        description="'cost_center' or 'account'.",
    )
    cost_center_id: Optional[int] = Field(
        None,
        description="Required when scope='cost_center'.  ID of the cost center to monitor.",
    )
    threshold_pct: int = Field(
        ...,
        ge=1,
        le=100,
        description="Alert when spend reaches this percentage of the budget (1–100).",
    )
    label: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional admin-friendly name, e.g. 'Engineering 80% warning'.",
    )


class BudgetAlertUpdate(BaseModel):
    """Partial update — only active alerts may be updated."""

    label: Optional[str] = Field(None, max_length=200)
    threshold_pct: Optional[int] = Field(None, ge=1, le=100)


class EvaluateAlertsRequest(BaseModel):
    """Request body for the evaluate endpoint."""

    billing_month: date = Field(
        ...,
        description="First day of the billing month to evaluate (YYYY-MM-DD).",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class BudgetAlertResponse(BaseModel):
    """Full representation of a single budget alert."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    corporate_account_id: int
    scope: str
    cost_center_id: Optional[int]
    cost_center_code: Optional[str] = None
    cost_center_name: Optional[str] = None
    threshold_pct: int
    label: Optional[str]
    status: str
    triggered_at: Optional[datetime]
    acknowledged_at: Optional[datetime]
    acknowledged_by_id: Optional[int]
    billing_month: Optional[date]
    spend_at_trigger_usd: Optional[Decimal]
    budget_at_trigger_usd: Optional[Decimal]
    created_at: datetime
    updated_at: datetime


class BudgetAlertListResponse(BaseModel):
    """Paginated list of budget alerts."""

    items: list[BudgetAlertResponse]
    total: int


class EvaluateAlertsResponse(BaseModel):
    """Result of running evaluate_budget_alerts."""

    triggered_count: int
    triggered_alerts: list[BudgetAlertResponse]
