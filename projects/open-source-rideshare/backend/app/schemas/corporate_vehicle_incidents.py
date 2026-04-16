"""Pydantic v2 schemas for Corporate Vehicle Incident Reports.

Fleet managers document vehicle incidents and track them through a
resolution workflow: draft → reported → under_review → resolved → closed.

Public surface
--------------
IncidentReportCreate        — payload for creating an incident report.
IncidentReportUpdate        — partial-update payload (mutable fields only).
IncidentReportResponse      — full incident report record returned by the API.
IncidentSummaryResponse     — aggregate counts and totals per account.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_vehicle_incident import IncidentStatus, IncidentType

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class IncidentReportCreate(BaseModel):
    """Payload for creating a corporate vehicle incident report.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle involved (required).
        incident_type: Category of the incident (required).
        incident_date: Calendar date the incident occurred (required).
        description: Full narrative of the incident (required).
        reported_by_id: UUID of the user submitting the report (required).
        incident_time: Time of day, nullable.
        incident_location: Location description, nullable (max 500 chars).
        estimated_damage_usd: Estimated cost in USD, nullable.
        police_report_number: Police reference number, nullable (max 100 chars).
        driver_id: UUID of the driver at time of incident, nullable.
        insurance_policy_id: UUID of the linked insurance policy, nullable.
        insurance_claim_number: Insurer-issued claim number, nullable (max 100 chars).
        witness_info: Witness names/contact details, nullable.
        notes: Admin notes, nullable.
    """

    fleet_vehicle_id: uuid.UUID
    incident_type: IncidentType
    incident_date: date
    description: str = Field(..., min_length=1)
    reported_by_id: int
    incident_time: Optional[time] = None
    incident_location: Optional[str] = Field(None, max_length=500)
    estimated_damage_usd: Optional[float] = Field(None, ge=0)
    police_report_number: Optional[str] = Field(None, max_length=100)
    driver_id: Optional[int] = None
    insurance_policy_id: Optional[uuid.UUID] = None
    insurance_claim_number: Optional[str] = Field(None, max_length=100)
    witness_info: Optional[str] = None
    notes: Optional[str] = None


class IncidentReportUpdate(BaseModel):
    """Partial-update payload for a vehicle incident report.

    All fields are optional.  fleet_vehicle_id and incident_type cannot
    be changed once the report has been created.  Updates are blocked once
    the report reaches ``resolved`` or ``closed`` status.
    """

    incident_date: Optional[date] = None
    incident_time: Optional[time] = None
    incident_location: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = Field(None, min_length=1)
    estimated_damage_usd: Optional[float] = Field(None, ge=0)
    police_report_number: Optional[str] = Field(None, max_length=100)
    driver_id: Optional[int] = None
    insurance_policy_id: Optional[uuid.UUID] = None
    insurance_claim_number: Optional[str] = Field(None, max_length=100)
    witness_info: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class IncidentReportResponse(BaseModel):
    """Full vehicle incident report record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    incident_type: str
    incident_status: str
    incident_date: date
    incident_time: Optional[time]
    incident_location: Optional[str]
    description: str
    estimated_damage_usd: Optional[float]
    police_report_number: Optional[str]
    driver_id: Optional[int]
    insurance_policy_id: Optional[uuid.UUID]
    insurance_claim_number: Optional[str]
    witness_info: Optional[str]
    reported_by_id: Optional[int]
    reviewed_by_id: Optional[int]
    resolved_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class IncidentSummaryResponse(BaseModel):
    """Aggregate incident statistics for a corporate account.

    Attributes:
        total_incidents: Total number of incident records.
        open_count: Incidents in draft, reported, or under_review status.
        by_status: Incident count keyed by IncidentStatus value.
        by_type: Incident count keyed by IncidentType value.
        total_estimated_damage_usd: Sum of estimated damages for open incidents.
    """

    total_incidents: int
    open_count: int
    by_status: Dict[str, int]
    by_type: Dict[str, int]
    total_estimated_damage_usd: float
