"""Pydantic v2 schemas for Corporate Policy Violations.

Violations are append-only audit records written when an employee's corporate
ride booking breaks the account's ride policy.  Admins can list, filter, and
acknowledge violations; platform-admins have cross-account views.

Public surface
--------------
ViolationType          — enum of violation categories.
ViolationCreate        — request body for manually recording a violation
                         (platform-admin or internal service use).
AcknowledgeRequest     — request body for acknowledging a single violation.
BulkAcknowledgeRequest — request body for bulk-acknowledging violations.
ViolationResponse      — full violation record returned by the API.
ViolationListResponse  — paginated list of violation records.
ViolationSummaryResponse — aggregate statistics for an account.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ViolationType(str, Enum):
    """Categories of ride-policy violation."""

    vehicle_type = "vehicle_type"
    per_ride_cost_exceeded = "per_ride_cost_exceeded"
    business_hours = "business_hours"
    missing_purpose = "missing_purpose"
    unapproved_purpose = "unapproved_purpose"
    spend_limit_exceeded = "spend_limit_exceeded"
    ride_quota_exceeded = "ride_quota_exceeded"
    blackout_period = "blackout_period"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ViolationCreate(BaseModel):
    """Request body for manually recording a policy violation.

    Primarily used by the platform-admin endpoint and internal service calls
    when the booking engine detects a violation.

    Attributes:
        member_id:         User ID of the employee whose booking violated policy.
        violation_type:    Category of violation.
        violation_details: Optional JSONB context — attempted values, policy
                           limits, etc.
        ride_id:           Optional ride FK (NULL for pre-booking denials).
        policy_snapshot:   Optional JSONB copy of the policy in effect at the
                           time of the violation.
    """

    member_id: int
    violation_type: ViolationType
    violation_details: Optional[Dict[str, Any]] = None
    ride_id: Optional[int] = None
    policy_snapshot: Optional[Dict[str, Any]] = None


class AcknowledgeRequest(BaseModel):
    """Request body for acknowledging a single policy violation.

    Attributes:
        acknowledgement_note: Optional note from the reviewing admin.
    """

    acknowledgement_note: Optional[str] = Field(None, max_length=2000)


class BulkAcknowledgeRequest(BaseModel):
    """Request body for bulk-acknowledging multiple violations.

    Attributes:
        violation_ids:       IDs of violations to acknowledge (1–100).
        acknowledgement_note: Note applied to all acknowledged violations.
    """

    violation_ids: List[int] = Field(..., min_length=1, max_length=100)
    acknowledgement_note: Optional[str] = Field(None, max_length=2000)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ViolationResponse(BaseModel):
    """Full violation record returned by the API.

    Attributes:
        id:                   Primary key.
        account_id:           Corporate account the violation belongs to.
        member_id:            Employee whose booking triggered the violation.
        ride_id:              Associated ride ID (null for pre-booking checks).
        violation_type:       Category string matching ViolationType enum.
        violation_details:    JSONB context from the policy check.
        policy_snapshot:      JSONB copy of the policy at time of violation.
        is_acknowledged:      True once an admin has reviewed the violation.
        acknowledged_by_id:   Admin who acknowledged (null if not acknowledged).
        acknowledged_at:      When the violation was acknowledged.
        acknowledgement_note: Note left by the acknowledging admin.
        created_at:           When the violation was recorded.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    member_id: int
    ride_id: Optional[int]
    violation_type: str
    violation_details: Optional[Dict[str, Any]]
    policy_snapshot: Optional[Dict[str, Any]]
    is_acknowledged: bool
    acknowledged_by_id: Optional[int]
    acknowledged_at: Optional[datetime]
    acknowledgement_note: Optional[str]
    created_at: datetime


class ViolationListResponse(BaseModel):
    """Paginated list of violation records.

    Attributes:
        violations: Violation records.
        total:      Number of records returned.
    """

    violations: List[ViolationResponse]
    total: int


class TopOffender(BaseModel):
    """Per-employee violation count for summary reporting.

    Attributes:
        member_id: Employee user ID.
        count:     Number of violations in the period.
    """

    member_id: int
    count: int


class ViolationSummaryResponse(BaseModel):
    """Aggregate violation statistics for a corporate account.

    Attributes:
        total_violations:  Total violations in the period.
        unacknowledged:    Violations not yet reviewed by an admin.
        by_type:           Violation count per type.
        top_offenders:     Top 5 employees with the most violations.
        period_days:       Number of days the summary covers.
    """

    total_violations: int
    unacknowledged: int
    by_type: Dict[str, int]
    top_offenders: List[TopOffender]
    period_days: int
