"""Pydantic v2 schemas for Corporate Account Suspension & Reinstatement.

Platform admins suspend corporate accounts for billing, compliance, or policy
reasons.  Reinstatement restores normal account operation.

Public surface
--------------
SuspendRequest          — body for suspending an account.
ReinstateRequest        — body for reinstating an account.
SuspensionResponse      — full suspension record returned by the API.
SuspensionStatusResponse — lightweight status response for members.
SuspensionListResponse  — paginated list of suspension records.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.models.corporate_account_suspension import SuspensionReason


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SuspendRequest(BaseModel):
    """Payload for suspending a corporate account.

    Attributes:
        reason: Structured reason category for the suspension.
        suspension_note: Optional free-text note from the admin.
    """

    reason: SuspensionReason
    suspension_note: Optional[str] = None


class ReinstateRequest(BaseModel):
    """Payload for reinstating a suspended corporate account.

    Attributes:
        reinstatement_note: Optional free-text note from the admin.
    """

    reinstatement_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SuspensionResponse(BaseModel):
    """Full suspension record returned by the API.

    Attributes:
        id: Primary key.
        account_id: Corporate account this suspension belongs to.
        suspended_by_id: Admin who created the suspension (null = system).
        reason: Structured suspension reason.
        suspension_note: Admin note explaining the suspension.
        suspended_at: When the suspension was created.
        reinstated_at: When reinstated; null if still active.
        reinstated_by_id: Admin who reinstated (null if still active).
        reinstatement_note: Note recorded on reinstatement.
        is_active: True while the suspension is in effect.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    suspended_by_id: Optional[int]
    reason: SuspensionReason
    suspension_note: Optional[str]
    suspended_at: datetime
    reinstated_at: Optional[datetime]
    reinstated_by_id: Optional[int]
    reinstatement_note: Optional[str]
    is_active: bool


class SuspensionStatusResponse(BaseModel):
    """Lightweight suspension status for a member's own account.

    Attributes:
        is_suspended: Whether the account is currently suspended.
        suspended_at: When the active suspension started (null if not suspended).
        reason: Reason category string (null if not suspended).
        suspension_note: Admin note (null if not suspended).
    """

    is_suspended: bool
    suspended_at: Optional[datetime]
    reason: Optional[str]
    suspension_note: Optional[str]


class SuspensionListResponse(BaseModel):
    """Paginated list of suspension records.

    Attributes:
        suspensions: List of suspension records.
        total: Total number of records matching the query.
    """

    suspensions: List[SuspensionResponse]
    total: int
