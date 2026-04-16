"""Pydantic v2 schemas for Corporate Multi-Currency Billing.

Corporate accounts can configure a preferred billing currency.  When invoices
are issued in a non-USD currency, an FX rate snapshot is stored for audit.

Public surface
--------------
BillingCurrencyCreate       — payload for creating a billing currency config.
BillingCurrencyUpdate       — partial-update payload.
BillingCurrencyResponse     — full billing currency config returned by the API.
FXSnapshotCreate            — payload for recording an FX snapshot.
FXSnapshotResponse          — full FX snapshot returned by the API.
FXSnapshotListResponse      — paginated list of FX snapshots.
CurrencySummaryResponse     — billing currency config + aggregate stats.
SetCurrencyRequest          — payload for the set-currency endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Allowed currency set (ISO 4217)
# ---------------------------------------------------------------------------

ALLOWED_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "SEK", "NOK", "DKK",
        "NZD", "SGD", "HKD", "MXN", "BRL", "ZAR", "INR", "KRW", "CNY", "AED",
    }
)


def _validate_currency(value: str) -> str:
    code = value.strip().upper()
    if code not in ALLOWED_CURRENCIES:
        raise ValueError(
            f"Currency '{value}' is not supported. "
            f"Allowed values: {sorted(ALLOWED_CURRENCIES)}"
        )
    return code


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class BillingCurrencyCreate(BaseModel):
    """Payload for creating a billing currency configuration.

    Attributes:
        billing_currency: ISO 4217 currency code.  Must be in the allowed set.
        auto_convert_invoices: When True, invoices get an FX rate snapshot.
        preferred_fx_provider: Optional audit label (e.g. "ECB", "Fixer").
    """

    billing_currency: str = Field("USD", min_length=3, max_length=3)
    auto_convert_invoices: bool = True
    preferred_fx_provider: Optional[str] = Field(None, max_length=50)

    @field_validator("billing_currency")
    @classmethod
    def validate_billing_currency(cls, v: str) -> str:
        return _validate_currency(v)


class BillingCurrencyUpdate(BaseModel):
    """Partial-update payload for billing currency configuration.

    All fields are optional.
    """

    billing_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    auto_convert_invoices: Optional[bool] = None
    preferred_fx_provider: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None

    @field_validator("billing_currency")
    @classmethod
    def validate_billing_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_currency(v)


class SetCurrencyRequest(BaseModel):
    """Payload for the set-currency endpoint.

    Attributes:
        currency: ISO 4217 currency code to set as the billing currency.
    """

    currency: str = Field(..., min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        return _validate_currency(v)


class FXSnapshotCreate(BaseModel):
    """Payload for recording an FX rate snapshot for an invoice.

    Attributes:
        exchange_rate: FX rate (USD → target currency) at the time of snapshot.
        rate_source: Optional audit label for where the rate came from.
    """

    exchange_rate: Decimal = Field(..., gt=0)
    rate_source: Optional[str] = Field(None, max_length=100)


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class BillingCurrencyResponse(BaseModel):
    """Full billing currency configuration returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    billing_currency: str
    auto_convert_invoices: bool
    preferred_fx_provider: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FXSnapshotResponse(BaseModel):
    """Full FX rate snapshot returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: int
    account_id: int
    source_currency: str
    target_currency: str
    exchange_rate: Decimal
    rate_captured_at: datetime
    rate_source: Optional[str]
    original_amount_usd: Decimal
    converted_amount: Decimal
    created_at: datetime


class FXSnapshotListResponse(BaseModel):
    """Paginated list of FX snapshots.

    Attributes:
        total: Total number of records matching the query.
        items: FX snapshot records for the current page.
    """

    total: int
    items: List[FXSnapshotResponse]


class CurrencySummaryResponse(BaseModel):
    """Billing currency config combined with aggregate stats.

    Attributes:
        config: The account's billing currency configuration.
        non_usd_invoice_count: Number of invoices that required FX conversion.
        total_converted_by_currency: Mapping of currency code → total
            converted amount for that currency (across all snapshots).
    """

    config: BillingCurrencyResponse
    non_usd_invoice_count: int
    total_converted_by_currency: dict[str, Decimal]
