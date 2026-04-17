"""Pydantic v2 schemas for Corporate Fleet Driver Assignments.

Fleet admins assign corporate account members to fleet vehicles, tracking
who drives each vehicle and recording the full assignment history.

Public surface
--------------
DriverAssignmentCreate   — payload for creating a driver assignment.
DriverAssignmentUpdate   — partial-update payload (end_date, notes, status).
EndAssignmentRequest     — body for the /end action endpoint.
DriverAssignmentResponse — full assignment record returned by the API.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_driver_assignment import (
    FleetDriverAssignmentStatus,
    FleetDriverAssignmentType,
)

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class DriverAssignmentCreate(BaseModel):
    """Payload for creating a fleet driver assignment.

    Attributes:
        vehicle_id: UUID of the fleet vehicle (required).
        user_id: ID of the user being assigned as a driver (required).
        assignment_type: Role classification for this assignment (required).
        start_date: Date the assignment becomes effective (required).
        end_date: Date the assignment ends; omit for indefinite, optional.
        authorized_by_user_id: ID of the user authorizing the assignment, optional.
        notes: Free-text notes, optional.
    """

    vehicle_id: uuid.UUID
    user_id: int
    assignment_type: FleetDriverAssignmentType
    start_date: date
    end_date: Optional[date] = None
    authorized_by_user_id: Optional[int] = None
    notes: Optional[str] = None


class DriverAssignmentUpdate(BaseModel):
    """Partial-update payload for a fleet driver assignment.

    All fields are optional; omitted fields are left unchanged.

    Attributes:
        end_date: New end date for the assignment, optional.
        notes: Updated free-text notes, optional.
        status: New lifecycle status, optional.
    """

    end_date: Optional[date] = None
    notes: Optional[str] = None
    status: Optional[FleetDriverAssignmentStatus] = None


class EndAssignmentRequest(BaseModel):
    """Optional body for the /end action endpoint.

    Attributes:
        end_date: Explicit end date; defaults to today if omitted, optional.
    """

    end_date: Optional[date] = Field(
        None, description="End date for the assignment; defaults to today."
    )


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class DriverAssignmentResponse(BaseModel):
    """Full fleet driver assignment record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    account_id: int
    user_id: int
    assignment_type: FleetDriverAssignmentType
    status: FleetDriverAssignmentStatus
    start_date: date
    end_date: Optional[date]
    authorized_by_user_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
