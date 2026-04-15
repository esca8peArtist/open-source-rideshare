"""Pydantic v2 schemas for the Corporate Account Onboarding Checklist feature.

The checklist is a read-only, computed response that helps new enterprise
account admins discover what setup steps have been completed and what remains
to be configured.  It is distinct from the account dashboard (which shows
operational metrics) and the admin audit log (which records past actions).

Public surface
--------------
OnboardingStep              — a single setup step with completion status.
OnboardingChecklistResponse — the full checklist for an account.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class OnboardingStep(BaseModel):
    """A single setup step in the corporate account onboarding checklist.

    Attributes:
        step_key:    Machine-readable identifier, e.g. "billing".
        title:       Short human-readable title for the step.
        description: One-line description of what this step configures.
        is_complete: True when the step's completion criteria are met.
        is_optional: Optional steps do not block ``all_required_complete``.
        action_hint: Suggested frontend route, e.g. "/corporate/billing".
    """

    step_key: str
    title: str
    description: str
    is_complete: bool
    is_optional: bool
    action_hint: str


class OnboardingChecklistResponse(BaseModel):
    """Computed onboarding checklist for a corporate account.

    Attributes:
        account_id:           The corporate account this checklist belongs to.
        total_steps:          Total number of steps (required + optional).
        required_steps:       Number of required steps.
        completed_required:   Number of required steps that are complete.
        completed_optional:   Number of optional steps that are complete.
        all_required_complete: True when every required step is complete.
        completion_pct:       ``completed_required / required_steps * 100``.
                              0.0 when there are no required steps.
        steps:                Ordered list of all steps (required first).
    """

    account_id: int
    total_steps: int
    required_steps: int
    completed_required: int
    completed_optional: int
    all_required_complete: bool
    completion_pct: float = Field(
        ...,
        description="Percentage of required steps that are complete (0–100).",
    )
    steps: list[OnboardingStep]
