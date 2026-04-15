"""Pydantic schemas for the Corporate Employee Invitation feature."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.corporate_employee_invitation import InvitationRole, InvitationStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

_DEFAULT_EXPIRY_DAYS = 7


class InvitationCreate(BaseModel):
    """Payload for creating a new employee invitation."""

    email: EmailStr = Field(..., description="Email address of the invitee.")
    role: InvitationRole = Field(
        InvitationRole.MEMBER,
        description="Role the invitee receives on acceptance.",
    )
    message: str | None = Field(
        None,
        max_length=1000,
        description="Optional personal note to include in the invitation.",
    )
    expires_at: datetime | None = Field(
        None,
        description=(
            f"UTC expiry datetime.  Defaults to {_DEFAULT_EXPIRY_DAYS} days "
            "from creation time when omitted."
        ),
    )

    @model_validator(mode="after")
    def _validate_expiry(self) -> "InvitationCreate":
        now = datetime.now(tz=timezone.utc)
        if self.expires_at is not None:
            exp = self.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                raise ValueError("expires_at must be in the future")
        return self


class InvitationRevoke(BaseModel):
    """Payload for revoking an invitation (currently no extra fields needed)."""

    pass


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class InvitationResponse(BaseModel):
    """Full representation of a corporate employee invitation."""

    id: uuid.UUID
    account_id: int
    token: uuid.UUID
    email: str
    invited_by_id: int
    role: InvitationRole
    message: str | None
    expires_at: datetime
    status: InvitationStatus
    accepted_at: datetime | None
    accepted_by_id: int | None
    revoked_at: datetime | None
    revoked_by_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationListResponse(BaseModel):
    """Paginated list of invitations."""

    items: list[InvitationResponse]
    total: int
    skip: int
    limit: int


class InvitationValidationResponse(BaseModel):
    """Result of validating an invitation token (public endpoint)."""

    is_valid: bool
    reason: str | None
    email: str | None
    role: InvitationRole | None
    account_name: str | None
    expires_at: datetime | None
