"""Pydantic schemas for corporate pre-paid credits."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.corporate_credit_account import CreditTransactionType


class CreditDepositRequest(BaseModel):
    """Request body for depositing credits into a corporate account."""

    amount_usd: Decimal = Field(..., gt=0, decimal_places=2)
    description: str = Field("", max_length=500)
    reference_id: Optional[str] = Field(None, max_length=200)
    reference_type: Optional[str] = Field(None, max_length=100)


class CreditRefundRequest(BaseModel):
    """Request body for refunding credits back to a corporate account."""

    amount_usd: Decimal = Field(..., gt=0, decimal_places=2)
    description: str = Field("", max_length=500)
    reference_id: Optional[str] = Field(None, max_length=200)
    reference_type: Optional[str] = Field(None, max_length=100)


class CreditAdjustRequest(BaseModel):
    """Request body for a platform-admin manual adjustment.

    ``signed_amount_usd`` may be negative to reduce the balance.
    """

    signed_amount_usd: Decimal = Field(..., decimal_places=2)
    description: str = Field("", max_length=500)
    reference_id: Optional[str] = Field(None, max_length=200)
    reference_type: Optional[str] = Field(None, max_length=100)

    @field_validator("signed_amount_usd")
    @classmethod
    def not_zero(cls, v: Decimal) -> Decimal:
        if v == Decimal("0"):
            raise ValueError("Adjustment amount must not be zero.")
        return v


class CreditThresholdRequest(BaseModel):
    """Request body for setting the low-balance alert threshold."""

    threshold_usd: Optional[Decimal] = Field(
        None,
        ge=0,
        decimal_places=2,
        description="Alert threshold in USD.  Pass null to disable.",
    )


class CreditTransactionResponse(BaseModel):
    """Single ledger entry (safe to return to clients)."""

    id: uuid.UUID
    account_id: int
    transaction_type: CreditTransactionType
    amount_usd: Decimal
    balance_after_usd: Decimal
    reference_id: Optional[str]
    reference_type: Optional[str]
    description: str
    created_by_id: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class CreditAccountResponse(BaseModel):
    """Current state of a corporate credit account."""

    id: int
    account_id: int
    balance_usd: Decimal
    total_deposited_usd: Decimal
    total_spent_usd: Decimal
    total_refunded_usd: Decimal
    low_balance_threshold_usd: Optional[Decimal]
    is_low_balance: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_flag(cls, obj) -> "CreditAccountResponse":
        """Build response and compute the ``is_low_balance`` flag."""
        is_low = (
            obj.low_balance_threshold_usd is not None
            and obj.balance_usd < obj.low_balance_threshold_usd
        )
        return cls(
            id=obj.id,
            account_id=obj.account_id,
            balance_usd=obj.balance_usd,
            total_deposited_usd=obj.total_deposited_usd,
            total_spent_usd=obj.total_spent_usd,
            total_refunded_usd=obj.total_refunded_usd,
            low_balance_threshold_usd=obj.low_balance_threshold_usd,
            is_low_balance=is_low,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class CreditTransactionListResponse(BaseModel):
    """Paginated list of ledger entries."""

    account_id: int
    total_returned: int
    items: list[CreditTransactionResponse]


class LowBalanceListResponse(BaseModel):
    """Platform-admin: accounts currently below their low-balance threshold."""

    total: int
    items: list[CreditAccountResponse]
