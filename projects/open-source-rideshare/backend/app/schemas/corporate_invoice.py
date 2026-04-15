"""Pydantic schemas for the Corporate Invoice feature."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CorporateInvoiceCreate(BaseModel):
    """Payload for generating a new monthly invoice."""

    period_start: date
    period_end: date
    notes: str | None = Field(None, max_length=500)

    @field_validator("period_end")
    @classmethod
    def period_end_not_before_start(cls, v: date, info) -> date:
        period_start = info.data.get("period_start")
        if period_start is not None and v < period_start:
            raise ValueError("period_end must be on or after period_start.")
        return v


class InvoiceMarkPaidRequest(BaseModel):
    """Optional payload when marking an invoice as paid."""

    notes: str | None = Field(None, max_length=500)


class CorporateInvoiceResponse(BaseModel):
    """Serialised invoice returned by the API."""

    id: int
    account_id: int
    invoice_number: str
    period_start: date
    period_end: date
    status: str
    total_rides: int
    subtotal_usd: Decimal
    notes: str | None
    generated_at: datetime
    finalized_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceLineItem(BaseModel):
    """A single ride entry within an invoice's line-item breakdown."""

    ride_id: int
    completed_at: datetime
    actual_fare: Decimal
    cost_center_id: int | None
    cost_center_name: str | None
    cost_center_code: str | None


class InvoiceLineItemsResponse(BaseModel):
    """Full line-item detail for an invoice, including per-cost-center summary."""

    invoice_id: int
    invoice_number: str
    period_start: date
    period_end: date
    total_rides: int
    subtotal_usd: Decimal
    line_items: list[InvoiceLineItem]
    by_cost_center: list[dict]  # [{cost_center_name, cost_center_code, ride_count, subtotal}]
