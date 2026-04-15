"""Pydantic schemas for Corporate API Keys."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    """Payload for creating a new corporate API key."""

    name: str = Field(..., description="Human-readable label for this key.")
    scopes: list[str] = Field(
        default_factory=list,
        description="Permission scope strings (e.g. 'rides:read', 'invoices:read').",
    )
    expires_at: Optional[datetime] = Field(
        None, description="Optional expiry datetime.  When omitted the key does not expire."
    )


class ApiKeyUpdate(BaseModel):
    """Payload for updating an API key.  All fields are optional."""

    name: Optional[str] = Field(None, description="New human-readable label.")
    scopes: Optional[list[str]] = Field(None, description="New scope list.")
    expires_at: Optional[datetime] = Field(None, description="New expiry datetime.")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ApiKeyResponse(BaseModel):
    """Representation of a corporate API key (key_hash excluded)."""

    id: uuid.UUID
    account_id: int
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyResponse):
    """Response returned at key creation or rotation — includes the plaintext key.

    The ``plain_key`` field is shown exactly once and cannot be retrieved later.
    """

    plain_key: str = Field(
        ...,
        description="The full API key value.  Store it securely — it will not be shown again.",
    )


class ApiKeyListResponse(BaseModel):
    """List of API keys for a corporate account."""

    account_id: int
    total: int
    keys: list[ApiKeyResponse]


class ApiKeyVerifyRequest(BaseModel):
    """Payload for verifying an API key (platform-admin endpoint)."""

    raw_key: str = Field(..., description="The full API key string to verify.")


class ApiKeyVerifyResponse(BaseModel):
    """Result of an API key verification."""

    valid: bool
    account_id: Optional[int] = None
    key_id: Optional[uuid.UUID] = None
    scopes: Optional[list[str]] = None
