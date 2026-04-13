"""Pydantic schemas for the driver onboarding status and activation workflow."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.driver_onboarding import OnboardingStatus


# ---------------------------------------------------------------------------
# Individual checklist item
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    """Status of a single onboarding requirement."""

    required: bool
    """Whether this item must be satisfied before activation."""

    met: bool
    """True when the requirement is currently satisfied."""

    detail: str
    """Human-readable explanation of the current state."""


# ---------------------------------------------------------------------------
# Full checklist response
# ---------------------------------------------------------------------------


class OnboardingChecklist(BaseModel):
    """Complete onboarding checklist returned to driver or admin."""

    driver_profile_id: int
    background_check: ChecklistItem
    driver_license: ChecklistItem
    vehicle_registration: ChecklistItem
    vehicle_inspection: ChecklistItem
    insurance_document: ChecklistItem
    profile_complete: ChecklistItem
    computed_status: OnboardingStatus
    """Status derived from the checklist — may differ from the persisted status
    if an admin has manually suspended the driver."""

    persisted_status: OnboardingStatus
    """Status stored in the database (may be ``suspended`` even when all checks pass)."""


# ---------------------------------------------------------------------------
# Admin action schemas
# ---------------------------------------------------------------------------


class ActivateDriverRequest(BaseModel):
    """Body for the activate-driver admin endpoint (currently no extra fields)."""

    pass


class SuspendDriverRequest(BaseModel):
    """Body for the suspend-driver admin endpoint."""

    reason: str

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must not be empty")
        return v.strip()


# ---------------------------------------------------------------------------
# Onboarding record response
# ---------------------------------------------------------------------------


class DriverOnboardingResponse(BaseModel):
    """Serialised DriverOnboarding ORM row."""

    id: int
    driver_profile_id: int
    status: OnboardingStatus
    suspension_reason: Optional[str]
    suspended_by: Optional[int]
    suspended_at: Optional[datetime]
    activated_by: Optional[int]
    activated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Paginated list helpers
# ---------------------------------------------------------------------------


class PendingDriverItem(BaseModel):
    """Summary row returned by the pending-review list endpoint."""

    driver_profile_id: int
    driver_user_id: int
    driver_name: str
    onboarding_id: int
    status: OnboardingStatus
    updated_at: datetime

    model_config = {"from_attributes": True}


class IncompleteDriverItem(BaseModel):
    """Summary row returned by the incomplete list endpoint."""

    driver_profile_id: int
    driver_user_id: int
    driver_name: str
    onboarding_id: int
    status: OnboardingStatus
    missing_steps: list[str]
    updated_at: datetime

    model_config = {"from_attributes": True}
