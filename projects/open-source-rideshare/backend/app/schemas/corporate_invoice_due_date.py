"""Pydantic schemas for corporate invoice due date and overdue tracking."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.corporate_invoice import InvoiceStatus


class SetInvoiceDueDateRequest(BaseModel):
    """Payload for setting or clearing a due date on an invoice."""

    due_date: date | None = None
    payment_terms_days: int | None = Field(
        None,
        ge=1,
        le=365,
        description="Number of days from finalization after which payment is due (1-365).",
    )


class OverdueInvoiceRow(BaseModel):
    """A single overdue invoice returned in list results."""

    invoice_id: int
    account_id: int
    invoice_number: str
    due_date: date
    days_overdue: int
    subtotal_usd: Decimal
    status: InvoiceStatus

    model_config = {"from_attributes": True}


class OverdueInvoicesResponse(BaseModel):
    """Response wrapper for overdue invoice lists."""

    invoices: list[OverdueInvoiceRow]
    total: int

    model_config = {"from_attributes": True}


class InvoiceOverdueScanResponse(BaseModel):
    """Summary returned after running the platform-wide overdue scan."""

    scanned: int
    overdue_count: int
    newly_flagged: int
    # Invoices that had no prior overdue note; now have one appended.
    as_of: date
