"""Pydantic schemas for Corporate Travel Policy & Acknowledgement.

Schemas:
  TravelPolicyCreate      — admin POST body to create a new policy version
  TravelPolicyUpdate      — admin PUT body for partial updates (draft only)
  TravelPolicyResponse    — full policy representation
  TravelPolicyListResponse — paginated list of policies
  AcknowledgementResponse — single acknowledgement record
  AcknowledgementSummary  — admin view: total members vs acknowledged counts
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Travel Policy schemas
# ---------------------------------------------------------------------------


class TravelPolicyCreate(BaseModel):
    """Fields required to create a new corporate travel policy."""

    title: str
    content: str
    version_number: str = "1"
    requires_acknowledgement: bool = True
    effective_date: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()

    @field_validator("content")
    @classmethod
    def content_min_length(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("content must be at least 10 characters")
        return v

    @field_validator("version_number")
    @classmethod
    def version_number_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("version_number must not be blank")
        return v.strip()


class TravelPolicyUpdate(BaseModel):
    """Partial update schema — only supplied fields are written.

    Updates are only allowed on inactive (draft) policies.  Attempting to
    update an active policy returns HTTP 409.
    """

    title: Optional[str] = None
    content: Optional[str] = None
    version_number: Optional[str] = None
    requires_acknowledgement: Optional[bool] = None
    effective_date: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("title must not be blank")
        return v.strip() if v is not None else v

    @field_validator("content")
    @classmethod
    def content_min_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.strip()) < 10:
            raise ValueError("content must be at least 10 characters")
        return v

    @field_validator("version_number")
    @classmethod
    def version_number_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("version_number must not be blank")
        return v.strip() if v is not None else v


class TravelPolicyResponse(BaseModel):
    """Full representation of a corporate travel policy."""

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    title: str
    content: str
    version_number: str
    is_active: bool
    requires_acknowledgement: bool
    effective_date: Optional[datetime]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class TravelPolicyListResponse(BaseModel):
    """Paginated list of travel policies."""

    items: list[TravelPolicyResponse]
    total: int


# ---------------------------------------------------------------------------
# Acknowledgement schemas
# ---------------------------------------------------------------------------


class AcknowledgementResponse(BaseModel):
    """A single policy acknowledgement record."""

    model_config = {"from_attributes": True}

    id: int
    policy_id: int
    member_id: Optional[int]
    account_id: int
    acknowledged_at: datetime


class AcknowledgementSummary(BaseModel):
    """Admin view of acknowledgement status for a policy.

    Attributes:
        policy_id: The policy being summarised.
        total_acknowledged: Number of members who have acknowledged.
        acknowledgements: Per-member acknowledgement records.
    """

    policy_id: int
    total_acknowledged: int
    acknowledgements: list[AcknowledgementResponse]


class MemberAcknowledgementStatus(BaseModel):
    """A member's acknowledgement status for the active policy.

    Attributes:
        member_id: The querying member.
        policy_id: The active policy (None if no active policy exists).
        has_acknowledged: True if the member has acknowledged the active policy.
        acknowledged_at: Timestamp of acknowledgement (None if not yet acked).
        requires_acknowledgement: Whether the active policy mandates acknowledgement.
    """

    member_id: int
    policy_id: Optional[int]
    has_acknowledged: bool
    acknowledged_at: Optional[datetime]
    requires_acknowledgement: bool
