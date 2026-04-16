"""Pydantic schemas for Corporate Member Offboarding.

Schemas:
  OffboardingCreate            — POST body to initiate an offboarding
  OffboardingUpdate            — PUT body for partial updates (reason/last_day/notes)
  ExecuteStepRequest           — POST body for execute-step endpoint
  CancelOffboardingRequest     — POST body for cancel endpoint (optional notes)
  OffboardingResponse          — full offboarding representation
  OffboardingListResponse      — list of offboarding records
  OffboardingStepDetail        — per-step status entry from steps_completed JSONB
  OffboardingSummaryResponse   — offboarding + step completion summary
  OffboardingOverviewItem      — lightweight overview item with step counts
  OffboardingOverviewResponse  — list of overview items
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.corporate_member_offboarding import OffboardingStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class OffboardingCreate(BaseModel):
    """Fields required to initiate a member offboarding workflow."""

    member_id: int
    reason: Optional[str] = None
    last_day: Optional[date] = None
    notes: Optional[str] = None


class OffboardingUpdate(BaseModel):
    """Partial update for reason, last_day, and notes fields."""

    reason: Optional[str] = None
    last_day: Optional[date] = None
    notes: Optional[str] = None


class ExecuteStepRequest(BaseModel):
    """Body for the execute-step endpoint."""

    step_name: str


class CancelOffboardingRequest(BaseModel):
    """Body for the cancel endpoint — notes are optional."""

    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class OffboardingResponse(BaseModel):
    """Full representation of a corporate member offboarding record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    member_id: Optional[int] = None
    member_email: str
    member_name: str
    initiated_by_id: Optional[int] = None
    status: OffboardingStatus
    reason: Optional[str] = None
    last_day: Optional[date] = None
    steps_completed: Dict[str, Any]
    notes: Optional[str] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OffboardingListResponse(BaseModel):
    """Paginated list of offboarding records."""

    items: List[OffboardingResponse]
    total: int


# ---------------------------------------------------------------------------
# Summary and overview schemas
# ---------------------------------------------------------------------------


class OffboardingStepDetail(BaseModel):
    """Status of a single offboarding cleanup step."""

    step_name: str
    completed: bool
    completed_at: Optional[datetime] = None
    completed_by_id: Optional[int] = None
    notes: Optional[str] = None
    count: int = 0


class OffboardingSummaryResponse(BaseModel):
    """Offboarding record enriched with step completion breakdown.

    Attributes:
        offboarding: Full offboarding record.
        total_steps: Total number of defined steps.
        completed_steps: Number of steps marked complete.
        pending_steps: Names of steps not yet completed.
        step_details: Per-step status detail list.
    """

    offboarding: OffboardingResponse
    total_steps: int
    completed_steps: int
    pending_steps: List[str]
    step_details: List[OffboardingStepDetail]


class OffboardingOverviewItem(BaseModel):
    """Lightweight overview of a single offboarding with step counts."""

    id: uuid.UUID
    account_id: int
    member_email: str
    member_name: str
    status: OffboardingStatus
    total_steps: int
    completed_steps: int
    last_day: Optional[date] = None
    created_at: datetime


class OffboardingOverviewResponse(BaseModel):
    """List of offboarding overview items for an account."""

    items: List[OffboardingOverviewItem]
    total: int
