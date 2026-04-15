"""Pydantic schemas for Corporate Billing Settings."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.corporate_billing_settings import BillingCycle, PaymentMethodType


# ---------------------------------------------------------------------------
# Billing Settings schemas
# ---------------------------------------------------------------------------


class BillingSettingsUpdate(BaseModel):
    """Request body for creating or updating corporate billing settings.

    All fields are optional — a PATCH-style partial update is supported.
    On first save an empty settings row is created; subsequent calls update it.
    """

    billing_company_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Legal entity name shown on invoices. Defaults to account name if null.",
    )
    billing_address_line1: Optional[str] = Field(
        None, max_length=200, description="Street address line 1."
    )
    billing_address_line2: Optional[str] = Field(
        None, max_length=200, description="Suite, floor, or building."
    )
    billing_city: Optional[str] = Field(None, max_length=100)
    billing_state: Optional[str] = Field(None, max_length=100)
    billing_postal_code: Optional[str] = Field(None, max_length=20)
    billing_country: Optional[str] = Field(
        None,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code, e.g. 'US'.",
    )
    tax_id: Optional[str] = Field(
        None,
        max_length=50,
        description="Tax ID / EIN / VAT number printed on invoices.",
    )
    po_number_required: Optional[bool] = Field(
        None,
        description="When True, invoices must include a PO number.",
    )
    default_po_number: Optional[str] = Field(
        None,
        max_length=100,
        description="Standing PO number pre-filled on all new invoices.",
    )
    invoice_memo_template: Optional[str] = Field(
        None,
        description="Boilerplate text appended to every invoice.",
    )
    auto_pay_enabled: Optional[bool] = Field(
        None,
        description="When True, finalized invoices are charged to the default payment method automatically.",
    )
    billing_cycle: Optional[BillingCycle] = Field(
        None,
        description="Frequency at which invoices are generated.",
    )
    invoice_emails: Optional[List[str]] = Field(
        None,
        description="Email addresses that receive invoice PDFs.",
    )


class BillingSettingsResponse(BaseModel):
    """Full billing settings for a corporate account."""

    id: int
    account_id: int
    billing_company_name: Optional[str]
    billing_address_line1: Optional[str]
    billing_address_line2: Optional[str]
    billing_city: Optional[str]
    billing_state: Optional[str]
    billing_postal_code: Optional[str]
    billing_country: Optional[str]
    tax_id: Optional[str]
    po_number_required: bool
    default_po_number: Optional[str]
    invoice_memo_template: Optional[str]
    auto_pay_enabled: bool
    billing_cycle: BillingCycle
    invoice_emails: Optional[List[str]]
    updated_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Payment Method schemas
# ---------------------------------------------------------------------------


class PaymentMethodCreate(BaseModel):
    """Request body for adding a new payment method to a corporate account."""

    payment_type: PaymentMethodType = Field(
        ..., description="Type of payment instrument."
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable label, e.g. 'Corporate Visa ending 4242'.",
    )
    last_four: Optional[str] = Field(
        None,
        min_length=4,
        max_length=4,
        description="Last four digits of card or bank account number.",
    )
    cardholder_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Name on the card or bank account.",
    )
    bank_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Bank name (for ACH / wire methods).",
    )
    external_payment_method_id: Optional[str] = Field(
        None,
        max_length=200,
        description="Gateway reference (e.g. Stripe PaymentMethod ID: pm_…).",
    )
    set_as_default: bool = Field(
        False,
        description="When True, this method becomes the account's default.",
    )


class PaymentMethodResponse(BaseModel):
    """A single corporate payment method."""

    id: int
    billing_settings_id: int
    account_id: int
    payment_type: PaymentMethodType
    display_name: str
    last_four: Optional[str]
    cardholder_name: Optional[str]
    bank_name: Optional[str]
    external_payment_method_id: Optional[str]
    is_default: bool
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Billing Summary schema
# ---------------------------------------------------------------------------


class BillingSummaryResponse(BaseModel):
    """Combined billing settings + payment method overview for an account."""

    settings: BillingSettingsResponse
    payment_methods: List[PaymentMethodResponse]
    default_payment_method: Optional[PaymentMethodResponse]
    has_complete_billing_address: bool
    has_tax_id: bool
    auto_pay_ready: bool  # auto_pay_enabled AND has a default payment method
