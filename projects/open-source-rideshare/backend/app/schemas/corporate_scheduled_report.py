"""Pydantic schemas for corporate scheduled reports."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.corporate_scheduled_report import ReportFrequency, ScheduledReportType


class ScheduledReportCreate(BaseModel):
    """Request body for creating a new scheduled report."""

    name: str = Field(..., min_length=1, max_length=200)
    report_type: ScheduledReportType
    frequency: ReportFrequency
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    recipients: list[str] = Field(default_factory=list, min_length=1)

    @field_validator("day_of_week")
    @classmethod
    def validate_day_of_week(cls, v: Optional[int], info) -> Optional[int]:
        return v

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one recipient email is required.")
        if len(v) > 50:
            raise ValueError("Maximum 50 recipients per scheduled report.")
        return [email.strip().lower() for email in v]


class ScheduledReportUpdate(BaseModel):
    """Request body for updating an existing scheduled report (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    report_type: Optional[ScheduledReportType] = None
    frequency: Optional[ReportFrequency] = None
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    recipients: Optional[list[str]] = None

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError("At least one recipient email is required.")
        if len(v) > 50:
            raise ValueError("Maximum 50 recipients per scheduled report.")
        return [email.strip().lower() for email in v]


class ScheduledReportResponse(BaseModel):
    """Full representation of a scheduled report (safe to return to clients)."""

    id: uuid.UUID
    account_id: int
    name: str
    report_type: ScheduledReportType
    frequency: ReportFrequency
    day_of_week: Optional[int]
    day_of_month: Optional[int]
    recipients: list[str]
    is_active: bool
    last_sent_at: Optional[datetime]
    next_due_at: Optional[datetime]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduledReportListResponse(BaseModel):
    """Paginated list of scheduled reports for an account."""

    account_id: int
    total: int
    items: list[ScheduledReportResponse]


class ScheduledReportTriggerResponse(BaseModel):
    """Result of a manual trigger (simulate delivery)."""

    report_id: uuid.UUID
    report_type: ScheduledReportType
    recipients: list[str]
    triggered_at: datetime
    message: str
