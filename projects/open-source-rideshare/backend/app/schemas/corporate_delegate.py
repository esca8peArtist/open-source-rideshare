"""Pydantic schemas for Corporate Delegate Access."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class DelegateCreate(BaseModel):
    """Payload for granting delegate access.

    A delegation allows *delegate_user_id* to book rides on behalf of
    *principal_user_id* within the corporate account.
    """

    principal_user_id: int = Field(
        ..., description="User ID of the principal (the person being booked for)."
    )
    delegate_user_id: int = Field(
        ..., description="User ID of the delegate (the person doing the booking)."
    )
    can_book_rides: bool = Field(
        True, description="When True, the delegate may book rides for the principal."
    )
    can_view_history: bool = Field(
        True,
        description="When True, the delegate may view the principal's corporate ride history.",
    )
    max_per_ride_usd: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Optional per-ride spend cap in USD.  Null means no cap.",
    )
    valid_until: Optional[datetime] = Field(
        None,
        description="Optional expiry datetime for the delegation.  Null means it never expires.",
    )

    @model_validator(mode="after")
    def principal_and_delegate_must_differ(self) -> DelegateCreate:
        if self.principal_user_id == self.delegate_user_id:
            raise ValueError("principal_user_id and delegate_user_id must be different users.")
        return self


class DelegateUpdate(BaseModel):
    """Payload for updating an existing delegation.  All fields are optional."""

    can_book_rides: Optional[bool] = None
    can_view_history: Optional[bool] = None
    max_per_ride_usd: Optional[Decimal] = Field(None, ge=0)
    valid_until: Optional[datetime] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DelegateResponse(BaseModel):
    """Full representation of a corporate delegation."""

    id: int
    account_id: int
    principal_id: int
    delegate_id: int
    can_book_rides: bool
    can_view_history: bool
    max_per_ride_usd: Optional[Decimal]
    valid_until: Optional[datetime]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DelegateListResponse(BaseModel):
    """Paginated list of delegations for a corporate account."""

    account_id: int
    total: int
    delegates: list[DelegateResponse]


# ---------------------------------------------------------------------------
# Permission check schemas
# ---------------------------------------------------------------------------


class DelegatePermissionCheck(BaseModel):
    """Payload for checking whether a delegate may book a ride for a principal."""

    delegate_user_id: int = Field(
        ..., description="User ID of the delegate attempting to book."
    )
    principal_user_id: int = Field(
        ..., description="User ID of the principal being booked for."
    )
    estimated_ride_cost_usd: Optional[Decimal] = Field(
        None,
        ge=0,
        description=(
            "Optional estimated ride cost in USD.  When provided and the delegation has "
            "a max_per_ride_usd cap, the cost is checked against the cap."
        ),
    )


class DelegatePermissionResult(BaseModel):
    """Result of a delegate permission check."""

    allowed: bool = Field(..., description="True when the delegate may proceed with the booking.")
    reason: str = Field(..., description="Human-readable explanation of the result.")
