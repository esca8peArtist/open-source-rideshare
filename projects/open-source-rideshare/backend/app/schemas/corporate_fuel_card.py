"""Pydantic schemas for corporate fuel card management."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.corporate_fuel_card import CardNetwork, FuelType


# ---------------------------------------------------------------------------
# Fuel Card schemas
# ---------------------------------------------------------------------------


class FuelCardCreateRequest(BaseModel):
    """Request body to issue a new company fuel card."""

    card_last_four: str = Field(
        ...,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="Last four digits of the card number.",
    )
    card_network: CardNetwork = Field(
        CardNetwork.OTHER,
        description="Card network / issuer type.",
    )
    nickname: str = Field(
        ...,
        max_length=100,
        description="Friendly label for the card, e.g. 'Van 2 WEX Card'.",
    )
    assigned_vehicle_id: Optional[uuid.UUID] = Field(
        None,
        description="Optional fleet vehicle to assign this card to.",
    )
    assigned_driver_id: Optional[int] = Field(
        None,
        description="Optional driver user ID to associate with this card.",
    )
    monthly_limit_usd: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Optional monthly spending cap in USD.",
    )
    notes: Optional[str] = Field(None, max_length=500)


class FuelCardUpdateRequest(BaseModel):
    """Request body to update a fuel card.  All fields optional."""

    card_last_four: Optional[str] = Field(
        None, min_length=4, max_length=4, pattern=r"^\d{4}$"
    )
    card_network: Optional[CardNetwork] = None
    nickname: Optional[str] = Field(None, max_length=100)
    monthly_limit_usd: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class FuelCardAssignVehicleRequest(BaseModel):
    """Request body to assign or re-assign a fuel card to a fleet vehicle."""

    vehicle_id: uuid.UUID = Field(..., description="Fleet vehicle UUID.")


class FuelCardAssignDriverRequest(BaseModel):
    """Request body to assign or re-assign a fuel card to a driver."""

    driver_id: int = Field(..., description="Driver user ID.")


class FuelCardResponse(BaseModel):
    """Full fuel card detail."""

    id: int
    account_id: int
    card_last_four: str
    card_network: CardNetwork
    nickname: str
    assigned_vehicle_id: Optional[uuid.UUID]
    assigned_driver_id: Optional[int]
    monthly_limit_usd: Optional[Decimal]
    is_active: bool
    issued_by_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FuelCardListResponse(BaseModel):
    """Paginated list of fuel cards."""

    total: int
    items: List[FuelCardResponse]


# ---------------------------------------------------------------------------
# Transaction schemas
# ---------------------------------------------------------------------------


class FuelTransactionCreateRequest(BaseModel):
    """Request body to record a fuel transaction."""

    transaction_date: date = Field(..., description="Date of the fuel purchase.")
    merchant_name: str = Field(
        ..., max_length=200, description="Name of the fuel station or charge point."
    )
    fuel_type: FuelType = Field(FuelType.OTHER, description="Type of fuel dispensed.")
    gallons: Optional[Decimal] = Field(
        None, ge=0, description="Volume in gallons (omit for EV or unknown)."
    )
    amount_usd: Decimal = Field(..., description="Total transaction cost in USD.")
    odometer_miles: Optional[int] = Field(
        None, ge=0, description="Vehicle odometer reading at time of purchase."
    )
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("amount_usd")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount_usd must be greater than 0")
        return v


class FuelTransactionResponse(BaseModel):
    """Full fuel transaction detail."""

    id: int
    fuel_card_id: int
    account_id: int
    transaction_date: date
    merchant_name: str
    fuel_type: FuelType
    gallons: Optional[Decimal]
    amount_usd: Decimal
    odometer_miles: Optional[int]
    notes: Optional[str]
    recorded_by_id: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class FuelTransactionListResponse(BaseModel):
    """Paginated list of fuel transactions."""

    total: int
    items: List[FuelTransactionResponse]


# ---------------------------------------------------------------------------
# Summary schemas
# ---------------------------------------------------------------------------


class FuelTypeBreakdown(BaseModel):
    """Spend breakdown for a single fuel type."""

    fuel_type: FuelType
    transaction_count: int
    total_gallons: Optional[Decimal]
    total_amount_usd: Decimal


class FuelCardSummaryResponse(BaseModel):
    """Aggregate statistics for a single fuel card."""

    card_id: int
    nickname: str
    is_active: bool
    monthly_limit_usd: Optional[Decimal]
    total_transactions: int
    total_amount_usd: Decimal
    current_month_amount_usd: Decimal
    monthly_limit_utilization_pct: Optional[Decimal]
    by_fuel_type: List[FuelTypeBreakdown]


class AccountFuelSummaryResponse(BaseModel):
    """Account-level aggregate fuel card statistics."""

    account_id: int
    total_cards: int
    active_cards: int
    total_transactions: int
    total_amount_usd: Decimal
    current_month_amount_usd: Decimal
    by_fuel_type: List[FuelTypeBreakdown]
