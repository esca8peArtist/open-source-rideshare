"""Pydantic v2 schemas for the Corporate Guest Pass feature.

Corporate employees issue guest passes — limited-use booking tokens — to
non-employees such as clients, candidates, or visitors.  Guests submit the
token when booking; no corporate login is required on their side.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class GuestPassCreate(BaseModel):
    """Payload for creating a new guest pass."""

    label: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable description, e.g. 'Client: ACME Interview'.",
    )
    max_uses: Optional[int] = Field(
        None,
        ge=1,
        description="Total allowed bookings.  Omit for unlimited.",
    )
    max_ride_budget_usd: Optional[Decimal] = Field(
        None,
        description="Per-ride spending cap in USD.  Omit for no cap.",
    )
    trip_purpose_id: Optional[int] = Field(
        None,
        description="Auto-tag rides created with this pass with this purpose code.",
    )
    cost_center_id: Optional[int] = Field(
        None,
        description="Bill rides created with this pass to this cost center.",
    )
    valid_from: Optional[datetime] = Field(
        None,
        description="Start of the validity window (UTC).  Defaults to now if omitted.",
    )
    valid_until: datetime = Field(
        ...,
        description="End of the validity window (UTC).  Must be in the future.",
    )

    @field_validator("valid_until")
    @classmethod
    def valid_until_must_be_future(cls, v: datetime) -> datetime:
        from datetime import timezone

        now = datetime.now(tz=timezone.utc)
        # Normalise naive datetimes to UTC for comparison
        if v.tzinfo is None:
            import warnings
            warnings.warn(
                "valid_until without timezone info is assumed UTC.",
                stacklevel=2,
            )
            v = v.replace(tzinfo=timezone.utc)
        if v <= now:
            raise ValueError("valid_until must be a future datetime.")
        return v


class GuestPassUpdate(BaseModel):
    """Payload for updating a guest pass.

    Only non-None fields are applied.  Cannot update revoked or exhausted passes.
    """

    label: Optional[str] = Field(None, min_length=1, max_length=200)
    max_uses: Optional[int] = Field(None, ge=1)
    max_ride_budget_usd: Optional[Decimal] = None
    valid_until: Optional[datetime] = Field(
        None,
        description="Extend or shorten the validity window.  Only applies to active passes.",
    )
    trip_purpose_id: Optional[int] = None
    cost_center_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class GuestPassResponse(BaseModel):
    """Full representation of a single guest pass, including the token."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: int
    created_by_employee_id: int
    token: uuid.UUID
    label: str
    max_uses: Optional[int]
    uses_remaining: Optional[int]
    max_ride_budget_usd: Optional[Decimal]
    trip_purpose_id: Optional[int]
    cost_center_id: Optional[int]
    valid_from: datetime
    valid_until: datetime
    status: str
    revoked_at: Optional[datetime]
    revoked_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    @property
    def total_uses(self) -> Optional[int]:
        """Number of times the pass has been used so far.

        Returns None when max_uses is None (unlimited).
        """
        if self.max_uses is None or self.uses_remaining is None:
            return None
        return self.max_uses - self.uses_remaining


class GuestPassValidationResponse(BaseModel):
    """Returned by the public token-validation endpoint.

    Exposes only the information a guest needs to confirm the pass is usable,
    without leaking internal account details.
    """

    is_valid: bool
    reason: Optional[str] = None
    label: Optional[str] = None
    max_ride_budget_usd: Optional[Decimal] = None
    account_name: Optional[str] = None
