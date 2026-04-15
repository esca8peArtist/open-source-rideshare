"""Pydantic schemas for the Corporate Employee Invitation feature."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.corporate_employee_invitation import InvitationRole, InvitationStatus

_BULK_MAX_ITEMS = 100


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


# ---------------------------------------------------------------------------
# Bulk invitation schemas
# ---------------------------------------------------------------------------


class BulkInvitationItem(BaseModel):
    """A single entry in a bulk invitation request."""

    email: EmailStr = Field(..., description="Email address of the invitee.")
    role: InvitationRole = Field(
        InvitationRole.MEMBER,
        description="Role the invitee receives on acceptance.",
    )
    message: str | None = Field(
        None,
        max_length=1000,
        description="Optional personal note to include in this invitation.",
    )


class BulkInvitationRequest(BaseModel):
    """Payload for creating multiple employee invitations in one request."""

    invitations: list[BulkInvitationItem] = Field(
        ...,
        min_length=1,
        max_length=_BULK_MAX_ITEMS,
        description=(
            f"List of invitations to create (1–{_BULK_MAX_ITEMS} items). "
            "Duplicate emails within the batch are processed in order; the "
            "second occurrence will be skipped once the first is pending."
        ),
    )
    expires_at: datetime | None = Field(
        None,
        description=(
            "Shared UTC expiry datetime applied to all items.  "
            "Defaults to 7 days from creation time when omitted."
        ),
    )

    @model_validator(mode="after")
    def _validate_expiry(self) -> "BulkInvitationRequest":
        now = datetime.now(tz=timezone.utc)
        if self.expires_at is not None:
            exp = self.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                raise ValueError("expires_at must be in the future")
        return self


class BulkInvitationItemResult(BaseModel):
    """Result for a single item in a bulk invitation request."""

    email: str
    role: InvitationRole
    status: Literal["created", "skipped", "error"] = Field(
        ...,
        description=(
            "'created' — invitation successfully created; "
            "'skipped' — already pending or email already an active member; "
            "'error' — unexpected failure for this item."
        ),
    )
    reason: str | None = Field(
        None,
        description="Human-readable explanation when status is 'skipped' or 'error'.",
    )
    invitation: InvitationResponse | None = Field(
        None,
        description="Full invitation object when status is 'created'.",
    )


class BulkInvitationResponse(BaseModel):
    """Summary and per-item results of a bulk invitation request."""

    total_requested: int
    total_created: int
    total_skipped: int
    total_errors: int
    results: list[BulkInvitationItemResult]
