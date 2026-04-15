"""Pydantic schemas for Corporate Admin Audit Log."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Audit log entry response
# ---------------------------------------------------------------------------


class AuditLogEntryResponse(BaseModel):
    """Full representation of a single corporate admin audit log entry."""

    id: int
    account_id: int
    actor_id: Optional[int] = Field(
        None,
        description="ID of the admin who performed the action.  Null for system-initiated events.",
    )
    action: str = Field(
        ...,
        description="Dot-namespaced action string, e.g. 'billing_contact.create'.",
    )
    resource_type: str = Field(
        ...,
        description="Resource category, e.g. 'billing_contact' or 'department'.",
    )
    resource_id: str = Field(
        ...,
        description="Identifier of the affected resource (int PK stored as string).",
    )
    details: Optional[dict[str, Any]] = Field(
        None,
        description="Optional JSONB payload with before/after values or extra context.",
    )
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Paginated list response
# ---------------------------------------------------------------------------


class AuditLogListResponse(BaseModel):
    """Paginated list of corporate admin audit log entries."""

    account_id: int
    total: int
    entries: list[AuditLogEntryResponse]
