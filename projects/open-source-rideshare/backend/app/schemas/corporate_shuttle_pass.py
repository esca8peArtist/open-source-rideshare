"""Pydantic v2 schemas for Corporate Shuttle Pass Management.

Enterprise accounts define pass types (ride count, validity window, price) and
issue passes to individual employees.  Employees redeem passes against shuttle
bookings; each redemption is recorded in a usage ledger.

Public surface
--------------
PassTypeCreateRequest   — payload for creating a shuttle pass type.
PassTypeUpdateRequest   — payload for updating a shuttle pass type.
PassTypeResponse        — full pass type returned by the API.
PassIssueRequest        — payload for issuing a pass to a member.
PassResponse            — full issued pass returned by the API.
PassRedeemRequest       — payload for redeeming a pass against a booking.
PassUsageResponse       — single pass usage record.
PassSummaryResponse     — aggregate account-level stats for shuttle passes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PassTypeCreateRequest(BaseModel):
    """Payload for creating a shuttle pass type.

    Attributes:
        name: Human-readable name (unique within the account).
        description: Optional description.
        ride_count: Number of rides included in each issued pass (≥ 1).
        validity_days: Days from issue date until expiry (nullable = no expiry).
        price_usd: Nominal cost for accounting purposes (nullable).
        notes: Optional free-text notes.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    ride_count: int = Field(..., ge=1)
    validity_days: Optional[int] = Field(None, ge=1)
    price_usd: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)


class PassTypeUpdateRequest(BaseModel):
    """Payload for updating a shuttle pass type.

    All fields are optional — only provided fields are updated.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    ride_count: Optional[int] = Field(None, ge=1)
    validity_days: Optional[int] = Field(None, ge=1)
    price_usd: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)


class PassTypeResponse(BaseModel):
    """Full shuttle pass type returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str]
    ride_count: int
    validity_days: Optional[int]
    price_usd: Optional[Decimal]
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class PassIssueRequest(BaseModel):
    """Payload for issuing a shuttle pass to a member.

    Attributes:
        pass_type_id: UUID of the pass type to issue.
        notes: Optional free-text notes for this pass instance.
    """

    pass_type_id: uuid.UUID
    notes: Optional[str] = Field(None, max_length=2000)


class PassResponse(BaseModel):
    """Full issued shuttle pass returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pass_type_id: uuid.UUID
    account_id: int
    member_id: Optional[int]
    rides_total: int
    rides_used: int
    rides_remaining: int
    issued_at: datetime
    expires_at: Optional[datetime]
    is_active: bool
    issued_by_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_pass(cls, row: object) -> "PassResponse":
        """Build from a CorporateShuttlePass ORM row."""
        return cls(
            id=row.id,  # type: ignore[attr-defined]
            pass_type_id=row.pass_type_id,  # type: ignore[attr-defined]
            account_id=row.account_id,  # type: ignore[attr-defined]
            member_id=row.member_id,  # type: ignore[attr-defined]
            rides_total=row.rides_total,  # type: ignore[attr-defined]
            rides_used=row.rides_used,  # type: ignore[attr-defined]
            rides_remaining=row.rides_total - row.rides_used,  # type: ignore[attr-defined]
            issued_at=row.issued_at,  # type: ignore[attr-defined]
            expires_at=row.expires_at,  # type: ignore[attr-defined]
            is_active=row.is_active,  # type: ignore[attr-defined]
            issued_by_id=row.issued_by_id,  # type: ignore[attr-defined]
            notes=row.notes,  # type: ignore[attr-defined]
            created_at=row.created_at,  # type: ignore[attr-defined]
            updated_at=row.updated_at,  # type: ignore[attr-defined]
        )


class PassRedeemRequest(BaseModel):
    """Payload for redeeming a shuttle pass against a booking.

    Attributes:
        booking_id: UUID of the shuttle booking to link this redemption to
            (nullable — redemption without a booking is allowed for manual
            adjustments).
    """

    booking_id: Optional[uuid.UUID] = None


class PassUsageResponse(BaseModel):
    """A single shuttle pass redemption record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pass_id: uuid.UUID
    account_id: int
    member_id: Optional[int]
    booking_id: Optional[uuid.UUID]
    redeemed_at: datetime
    rides_remaining_after: int
    created_at: datetime


class PassSummaryResponse(BaseModel):
    """Aggregate shuttle pass statistics for a corporate account.

    Attributes:
        account_id: Corporate account ID.
        total_pass_types: Number of pass types defined (active + inactive).
        active_pass_types: Number of active pass types.
        total_passes_issued: Total passes ever issued.
        active_passes: Passes currently active (is_active=True).
        expired_passes: Passes that have passed their expires_at.
        total_rides_issued: Sum of rides_total across all passes.
        total_rides_used: Sum of rides_used across all passes.
        total_rides_remaining: total_rides_issued - total_rides_used.
    """

    account_id: int
    total_pass_types: int
    active_pass_types: int
    total_passes_issued: int
    active_passes: int
    expired_passes: int
    total_rides_issued: int
    total_rides_used: int
    total_rides_remaining: int
