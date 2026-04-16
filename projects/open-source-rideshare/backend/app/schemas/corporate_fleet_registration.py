"""Pydantic v2 schemas for Corporate Fleet Vehicle Registration Tracking.

Fleet managers track state/jurisdiction registration records for company
vehicles with expiry date alerts.

Public surface
--------------
RegistrationCreate          — payload for creating a vehicle registration record.
RegistrationUpdate          — partial-update payload.
RegistrationResponse        — full registration record returned by the API.
RegistrationExpiringResponse — expiry alert entry with days_until_expiry always populated.
RegistrationSummaryResponse  — aggregate counts and totals per account.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class RegistrationCreate(BaseModel):
    """Payload for creating a fleet vehicle registration record.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle (required).
        registration_number: DMV registration document number (required, 1–100 chars).
        registration_state: State or jurisdiction (required, 1–100 chars).
        registration_date: Date when the vehicle was registered (required).
        expiration_date: Date when the registration expires (required).
        annual_fee_usd: Annual registration fee in USD, nullable.
        registered_owner_name: Legal owner name on title, nullable (1–200 chars).
        notes: Optional free-text notes.
    """

    fleet_vehicle_id: uuid.UUID
    registration_number: str = Field(..., min_length=1, max_length=100)
    registration_state: str = Field(..., min_length=1, max_length=100)
    registration_date: date
    expiration_date: date
    annual_fee_usd: Optional[float] = Field(None, ge=0)
    registered_owner_name: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None


class RegistrationUpdate(BaseModel):
    """Partial-update payload for a fleet vehicle registration record.

    All fields are optional.  fleet_vehicle_id cannot be changed once created.
    """

    registration_number: Optional[str] = Field(None, min_length=1, max_length=100)
    registration_state: Optional[str] = Field(None, min_length=1, max_length=100)
    registration_date: Optional[date] = None
    expiration_date: Optional[date] = None
    annual_fee_usd: Optional[float] = Field(None, ge=0)
    registered_owner_name: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class RegistrationResponse(BaseModel):
    """Full fleet vehicle registration record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    registration_number: str
    registration_state: str
    registration_date: date
    expiration_date: date
    annual_fee_usd: Optional[float]
    registered_owner_name: Optional[str]
    is_active: bool
    notes: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    days_until_expiry: Optional[int] = None


class RegistrationExpiringResponse(BaseModel):
    """A registration record expiring soon, with days_until_expiry always populated.

    Attributes:
        id: UUID of the registration record.
        fleet_vehicle_id: UUID of the vehicle.
        registration_number: DMV registration document number.
        registration_state: State or jurisdiction.
        expiration_date: Date the registration expires.
        days_until_expiry: Whole days remaining until expiration_date from today.
    """

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    registration_number: str
    registration_state: str
    registration_date: date
    expiration_date: date
    annual_fee_usd: Optional[float]
    registered_owner_name: Optional[str]
    is_active: bool
    notes: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    days_until_expiry: int


class RegistrationSummaryResponse(BaseModel):
    """Aggregate registration statistics for a corporate account.

    Attributes:
        active_count: Number of active registration records.
        inactive_count: Number of inactive registration records.
        expiring_within_30_days: Active registrations expiring within 30 days.
        total_annual_fee_usd: Sum of annual fees for active registrations.
        per_state_breakdown: Registration count keyed by state/jurisdiction name.
    """

    active_count: int
    inactive_count: int
    expiring_within_30_days: int
    total_annual_fee_usd: float
    per_state_breakdown: Dict[str, int]
