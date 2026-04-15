"""Pydantic schemas for GDPR/CCPA Privacy Compliance endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.privacy import DeletionStatus, ExportStatus, PolicyType


# ---------------------------------------------------------------------------
# Consent schemas
# ---------------------------------------------------------------------------


class RecordConsentRequest(BaseModel):
    """Request body for recording a user's consent decision."""

    policy_type: PolicyType
    policy_version: str = Field(..., min_length=1, max_length=50)
    consented: bool
    ip_address: Optional[str] = Field(None, max_length=45)
    user_agent: Optional[str] = Field(None, max_length=512)


class ConsentRecordResponse(BaseModel):
    """Response schema for a single consent record."""

    model_config = {"from_attributes": True}

    id: int
    user_id: int
    policy_type: PolicyType
    policy_version: str
    consented: bool
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    consented_at: datetime


# ---------------------------------------------------------------------------
# Data export schemas
# ---------------------------------------------------------------------------


class DataExportRequestResponse(BaseModel):
    """Response schema for a data export request."""

    model_config = {"from_attributes": True}

    id: int
    user_id: int
    status: ExportStatus
    requested_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    download_count: int
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Account deletion schemas
# ---------------------------------------------------------------------------


class RequestDeletionBody(BaseModel):
    """Optional request body for initiating account deletion."""

    reason: Optional[str] = Field(None, max_length=1000)


class DeletionRequestResponse(BaseModel):
    """Response schema for an account deletion request."""

    model_config = {"from_attributes": True}

    id: int
    user_id: int
    status: DeletionStatus
    reason: Optional[str] = None
    requested_at: datetime
    scheduled_for: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
