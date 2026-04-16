"""Pydantic v2 schemas for Corporate Parking Management.

Enterprise accounts manage physical parking facilities, individual spots, and
spot assignments for employees.

Public surface
--------------
FacilityCreate          — payload for creating a parking facility.
FacilityUpdate          — partial-update payload for a facility.
FacilityResponse        — full facility returned by the API.
SpotCreate              — payload for adding a parking spot to a facility.
SpotUpdate              — partial-update payload for a spot.
SpotResponse            — full spot returned by the API.
AssignmentCreate        — payload for assigning a spot to a member.
AssignmentResponse      — full assignment returned by the API.
FacilitySummaryResponse — aggregate stats for a parking facility.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_parking import FacilityType, SpotType


# ---------------------------------------------------------------------------
# Facility schemas
# ---------------------------------------------------------------------------


class FacilityCreate(BaseModel):
    """Payload for creating a parking facility.

    Attributes:
        name: Human-readable facility name (required, unique per account).
        description: Optional description.
        address_line1: Street address.
        address_line2: Suite / floor / unit (optional).
        city: City.
        state: State or province.
        zip_code: Postal code.
        lat: Latitude string (optional).
        lng: Longitude string (optional).
        facility_type: Enum — surface_lot / parking_garage / covered_structure / underground.
        notes: Free-text notes.
    """

    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    address_line1: Optional[str] = Field(None, max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    zip_code: Optional[str] = Field(None, max_length=20)
    lat: Optional[str] = Field(None, max_length=20)
    lng: Optional[str] = Field(None, max_length=20)
    facility_type: FacilityType = FacilityType.surface_lot
    notes: Optional[str] = None


class FacilityUpdate(BaseModel):
    """Partial-update payload for a parking facility."""

    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None
    address_line1: Optional[str] = Field(None, max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    zip_code: Optional[str] = Field(None, max_length=20)
    lat: Optional[str] = Field(None, max_length=20)
    lng: Optional[str] = Field(None, max_length=20)
    facility_type: Optional[FacilityType] = None
    notes: Optional[str] = None


class FacilityResponse(BaseModel):
    """Full parking facility returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    lat: Optional[str]
    lng: Optional[str]
    facility_type: FacilityType
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Spot schemas
# ---------------------------------------------------------------------------


class SpotCreate(BaseModel):
    """Payload for adding a parking spot to a facility.

    Attributes:
        facility_id: UUID of the parent facility.
        spot_identifier: Human-readable spot label (e.g., "A-12"), unique per facility.
        spot_type: Enum — standard / accessible / ev_charging / motorcycle / oversized / reserved / visitor.
        floor_level: Optional floor label (e.g., "1", "B2").
        notes: Free-text notes.
    """

    facility_id: uuid.UUID
    spot_identifier: str = Field(..., min_length=1, max_length=50)
    spot_type: SpotType = SpotType.standard
    floor_level: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None


class SpotUpdate(BaseModel):
    """Partial-update payload for a parking spot."""

    spot_identifier: Optional[str] = Field(None, min_length=1, max_length=50)
    spot_type: Optional[SpotType] = None
    floor_level: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None


class SpotResponse(BaseModel):
    """Full parking spot returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    facility_id: uuid.UUID
    spot_identifier: str
    spot_type: SpotType
    floor_level: Optional[str]
    is_assigned: bool
    notes: Optional[str]
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Assignment schemas
# ---------------------------------------------------------------------------


class AssignmentCreate(BaseModel):
    """Payload for assigning a spot to a member.

    Attributes:
        member_id: User ID of the employee receiving the spot.
        permit_number: Optional external permit reference.
        start_date: Date the assignment becomes effective.
        end_date: Optional expiry date (None = open-ended / permanent).
        notes: Free-text notes.
    """

    member_id: int
    permit_number: Optional[str] = Field(None, max_length=100)
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None


class AssignmentResponse(BaseModel):
    """Full parking assignment returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    spot_id: uuid.UUID
    member_id: Optional[int]
    assigned_by_id: Optional[int]
    permit_number: Optional[str]
    start_date: date
    end_date: Optional[date]
    is_active: bool
    notes: Optional[str]
    ended_at: Optional[datetime]
    ended_by_id: Optional[int]
    created_at: datetime


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class FacilitySummaryResponse(BaseModel):
    """Aggregate statistics for a parking facility.

    Attributes:
        facility_id: UUID of the facility.
        total_spots: Total number of spots (active + inactive).
        active_spots: Number of currently active spots.
        assigned_spots: Number of active spots currently assigned.
        available_spots: Number of active spots not currently assigned.
        by_spot_type: Breakdown of active spot counts by type.
    """

    facility_id: uuid.UUID
    total_spots: int
    active_spots: int
    assigned_spots: int
    available_spots: int
    by_spot_type: Dict[str, int]
