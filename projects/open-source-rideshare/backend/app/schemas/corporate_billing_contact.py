"""Pydantic schemas for Corporate Billing Contact Management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Billing Contact CRUD
# ---------------------------------------------------------------------------


class BillingContactCreate(BaseModel):
    """Payload for adding a new billing contact to a corporate account."""

    name: str = Field(..., min_length=1, max_length=200, description="Display name of the contact.")
    email: str = Field(..., description="Contact email address.  Normalised to lowercase.")
    phone: Optional[str] = Field(None, max_length=50, description="Optional phone number.")
    role: Optional[str] = Field(
        None, max_length=100, description="Optional free-text role label (e.g. 'AP Manager')."
    )
    receives_invoices: bool = Field(
        True, description="Opt-in to invoice emails."
    )
    receives_budget_alerts: bool = Field(
        False, description="Opt-in to budget alert emails."
    )
    receives_monthly_summary: bool = Field(
        False, description="Opt-in to monthly summary emails."
    )

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class BillingContactUpdate(BaseModel):
    """Payload for updating a billing contact.

    All fields are optional.  The email address is immutable after creation
    and is therefore not included here.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    role: Optional[str] = Field(None, max_length=100)
    receives_invoices: Optional[bool] = None
    receives_budget_alerts: Optional[bool] = None
    receives_monthly_summary: Optional[bool] = None


class BillingContactResponse(BaseModel):
    """Full representation of a billing contact."""

    id: int
    account_id: int
    name: str
    email: str
    phone: Optional[str]
    role: Optional[str]
    receives_invoices: bool
    receives_budget_alerts: bool
    receives_monthly_summary: bool
    is_active: bool
    added_by_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BillingContactListResponse(BaseModel):
    """Paginated list of billing contacts for a corporate account."""

    account_id: int
    total: int
    contacts: list[BillingContactResponse]
