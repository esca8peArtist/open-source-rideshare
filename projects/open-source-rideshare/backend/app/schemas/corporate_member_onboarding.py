"""Pydantic schemas for Corporate Member Onboarding.

Schemas:
  OnboardingCreate            — POST body to create an onboarding tracker
  OnboardingUpdate            — PUT body for partial updates (notes)
  MarkStepRequest             — POST body for mark-step endpoint
  OnboardingResponse          — full onboarding representation
  OnboardingListResponse      — list of onboarding records
  OnboardingStepDetail        — per-step status entry from steps_completed JSONB
  OnboardingSummaryResponse   — onboarding + step completion summary
  OnboardingOverviewItem      — lightweight overview item with step counts
  OnboardingOverviewResponse  — list of overview items
  AutoDetectResult            — result of auto-detect progress scan
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.corporate_member_onboarding import OnboardingStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class OnboardingCreate(BaseModel):
    """Fields required to create a member onboarding tracker."""

    member_id: int
    invitation_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class OnboardingUpdate(BaseModel):
    """Partial update for notes field."""

    notes: Optional[str] = None


class MarkStepRequest(BaseModel):
    """Body for the mark-step endpoint."""

    step_name: str
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class OnboardingResponse(BaseModel):
    """Full representation of a corporate member onboarding record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    member_id: Optional[int] = None
    member_email: str
    member_name: str
    invitation_id: Optional[uuid.UUID] = None
    created_by_id: Optional[int] = None
    status: OnboardingStatus
    steps_completed: Dict[str, Any]
    notes: Optional[str] = None
    completed_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OnboardingListResponse(BaseModel):
    """Paginated list of onboarding records."""

    items: List[OnboardingResponse]
    total: int


# ---------------------------------------------------------------------------
# Summary and overview schemas
# ---------------------------------------------------------------------------


class OnboardingStepDetail(BaseModel):
    """Status of a single onboarding setup step."""

    step_name: str
    completed: bool
    completed_at: Optional[datetime] = None
    completed_by_id: Optional[int] = None
    notes: Optional[str] = None
    auto_detected: bool = False


class OnboardingSummaryResponse(BaseModel):
    """Onboarding record enriched with step completion breakdown.

    Attributes:
        onboarding: Full onboarding record.
        total_steps: Total number of defined steps.
        completed_steps: Number of steps marked complete.
        pending_steps: Names of steps not yet completed.
        step_details: Per-step status detail list.
    """

    onboarding: OnboardingResponse
    total_steps: int
    completed_steps: int
    pending_steps: List[str]
    step_details: List[OnboardingStepDetail]


class OnboardingOverviewItem(BaseModel):
    """Lightweight overview of a single onboarding with step counts."""

    id: uuid.UUID
    account_id: int
    member_email: str
    member_name: str
    status: OnboardingStatus
    total_steps: int
    completed_steps: int
    created_at: datetime


class OnboardingOverviewResponse(BaseModel):
    """List of onboarding overview items for an account."""

    items: List[OnboardingOverviewItem]
    total: int


class AutoDetectResult(BaseModel):
    """Result of an auto-detect progress scan.

    Attributes:
        newly_detected: Steps that were auto-detected as complete in this scan.
        already_completed: Steps that were already marked complete before the scan.
        still_pending: Steps not yet complete after the scan.
        onboarding: Updated onboarding record.
    """

    newly_detected: List[str]
    already_completed: List[str]
    still_pending: List[str]
    onboarding: OnboardingResponse
