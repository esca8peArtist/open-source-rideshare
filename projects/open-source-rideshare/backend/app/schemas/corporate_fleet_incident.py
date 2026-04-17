"""Pydantic v2 schemas for Corporate Fleet Incident Reports.

Fleet members log vehicle incidents and fleet admins manage them through
review, resolution, and closure.

Public surface
--------------
IncidentReportCreate          — payload for logging a new incident report.
IncidentReportUpdate          — partial-update payload (admin only).
IncidentReportResponse        — full incident report returned by the API.
VehicleIncidentSummaryResponse — per-vehicle aggregate stats.
AccountIncidentSummaryResponse — account-wide aggregate stats.
PlatformIncidentOverviewResponse — platform-wide aggregate stats (platform admin).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_incident import (
    FleetIncidentSeverity,
    FleetIncidentStatus,
    FleetIncidentType,
)

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class IncidentReportCreate(BaseModel):
    """Payload for logging a new fleet vehicle incident report.

    Attributes:
        vehicle_id: UUID of the fleet vehicle involved, optional (SET NULL if removed).
        incident_type: Category of the incident (required).
        severity: Severity level of the incident (required).
        incident_date: Date the incident occurred (required).
        incident_location: Location description, optional (max 500 chars).
        description: Free-text description of the incident, optional.
        damage_estimate: Estimated damage cost in USD, optional.
        insurance_claim_number: Insurance claim reference number, optional.
        police_report_number: Police report reference number, optional.
        third_party_involved: Whether a third party was involved, default False.
        injuries_reported: Whether injuries were reported, default False.
    """

    vehicle_id: Optional[uuid.UUID] = None
    incident_type: FleetIncidentType
    severity: FleetIncidentSeverity
    incident_date: date
    incident_location: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    damage_estimate: Optional[float] = Field(None, ge=0)
    insurance_claim_number: Optional[str] = Field(None, max_length=100)
    police_report_number: Optional[str] = Field(None, max_length=100)
    third_party_involved: bool = False
    injuries_reported: bool = False


class IncidentReportUpdate(BaseModel):
    """Partial-update payload for a fleet incident report.

    All fields are optional.  Admin-only operation.
    """

    vehicle_id: Optional[uuid.UUID] = None
    incident_type: Optional[FleetIncidentType] = None
    severity: Optional[FleetIncidentSeverity] = None
    status: Optional[FleetIncidentStatus] = None
    incident_date: Optional[date] = None
    incident_location: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    damage_estimate: Optional[float] = Field(None, ge=0)
    insurance_claim_number: Optional[str] = Field(None, max_length=100)
    police_report_number: Optional[str] = Field(None, max_length=100)
    third_party_involved: Optional[bool] = None
    injuries_reported: Optional[bool] = None
    resolution_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class IncidentReportResponse(BaseModel):
    """Full fleet incident report returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    vehicle_id: Optional[uuid.UUID]
    reported_by_user_id: Optional[int]
    incident_type: FleetIncidentType
    severity: FleetIncidentSeverity
    status: FleetIncidentStatus
    incident_date: date
    incident_location: Optional[str]
    description: Optional[str]
    damage_estimate: Optional[float]
    insurance_claim_number: Optional[str]
    police_report_number: Optional[str]
    third_party_involved: bool
    injuries_reported: bool
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class IncidentTypeBreakdown(BaseModel):
    """Per-type breakdown entry for incident summary.

    Attributes:
        incident_type: The category of incident.
        count: Number of reports for this type.
        total_damage_estimate: Sum of damage estimates for this type.
    """

    incident_type: FleetIncidentType
    count: int
    total_damage_estimate: float


class IncidentSeverityBreakdown(BaseModel):
    """Per-severity breakdown entry for incident summary.

    Attributes:
        severity: The severity level.
        count: Number of reports at this severity level.
    """

    severity: FleetIncidentSeverity
    count: int


class IncidentStatusBreakdown(BaseModel):
    """Per-status breakdown entry for incident summary.

    Attributes:
        status: The incident lifecycle status.
        count: Number of reports at this status.
    """

    status: FleetIncidentStatus
    count: int


class VehicleIncidentSummaryResponse(BaseModel):
    """Aggregate incident statistics for a single fleet vehicle.

    Attributes:
        vehicle_id: UUID of the fleet vehicle.
        total: Total number of incident reports for this vehicle.
        by_type: Per-incident-type breakdown list.
        by_severity: Per-severity breakdown list.
        by_status: Per-status breakdown list.
        total_damage_estimate: Sum of all damage estimates for this vehicle.
    """

    vehicle_id: uuid.UUID
    total: int
    by_type: List[IncidentTypeBreakdown]
    by_severity: List[IncidentSeverityBreakdown]
    by_status: List[IncidentStatusBreakdown]
    total_damage_estimate: float


class AccountIncidentSummaryResponse(BaseModel):
    """Account-wide aggregate incident statistics.

    Attributes:
        account_id: Corporate account ID.
        total: Total incident reports for this account.
        by_type: Per-incident-type breakdown list.
        by_severity: Per-severity breakdown list.
        by_status: Per-status breakdown list.
        total_damage_estimate: Sum of all damage estimates for this account.
    """

    account_id: int
    total: int
    by_type: List[IncidentTypeBreakdown]
    by_severity: List[IncidentSeverityBreakdown]
    by_status: List[IncidentStatusBreakdown]
    total_damage_estimate: float


class PlatformIncidentOverviewResponse(BaseModel):
    """Platform-wide aggregate incident statistics (platform admin only).

    Attributes:
        total: Total incident reports across all accounts.
        by_type: Per-incident-type breakdown list.
        by_severity: Per-severity breakdown list.
        by_status: Per-status breakdown list.
        total_damage_estimate: Sum of all damage estimates across all accounts.
        total_accounts_with_incidents: Number of accounts with at least one incident.
    """

    total: int
    by_type: List[IncidentTypeBreakdown]
    by_severity: List[IncidentSeverityBreakdown]
    by_status: List[IncidentStatusBreakdown]
    total_damage_estimate: float
    total_accounts_with_incidents: int
