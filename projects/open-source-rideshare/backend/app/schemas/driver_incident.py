"""Pydantic schemas for driver incident reports."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.driver_incident import IncidentSeverity, IncidentStatus, IncidentType


class DriverIncidentCreate(BaseModel):
    incident_type: IncidentType
    severity: IncidentSeverity = IncidentSeverity.medium
    description: str = Field(..., min_length=10, max_length=5000)
    ride_id: Optional[int] = None
    # Caller passes a list of URLs; we join to string internally
    evidence_urls: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("evidence_urls")
    @classmethod
    def validate_urls(cls, v: list[str]) -> list[str]:
        for url in v:
            if len(url) > 500:
                raise ValueError("Each evidence URL must be 500 characters or fewer.")
        return v


class DriverIncidentUpdate(BaseModel):
    """Driver can only update description and evidence before admin review starts."""

    description: Optional[str] = Field(None, min_length=10, max_length=5000)
    evidence_urls: Optional[list[str]] = Field(None, max_length=10)

    @field_validator("evidence_urls")
    @classmethod
    def validate_urls(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for url in v:
            if len(url) > 500:
                raise ValueError("Each evidence URL must be 500 characters or fewer.")
        return v


class AdminIncidentReview(BaseModel):
    """Admin: move to under_review with an optional initial note."""

    admin_note: Optional[str] = Field(None, max_length=1000)


class AdminIncidentResolve(BaseModel):
    """Admin: resolve an incident."""

    admin_note: Optional[str] = Field(None, max_length=1000)


class AdminIncidentDismiss(BaseModel):
    """Admin: dismiss an incident (not actionable / duplicate / bad faith)."""

    admin_note: Optional[str] = Field(None, max_length=1000)


class DriverIncidentResponse(BaseModel):
    id: int
    driver_id: int
    ride_id: Optional[int]
    incident_type: IncidentType
    severity: IncidentSeverity
    status: IncidentStatus
    description: str
    evidence_urls: list[str]
    admin_note: Optional[str]
    reviewed_by_id: Optional[int]
    reviewed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj: object) -> "DriverIncidentResponse":
        """Build response, splitting the stored evidence_urls string back to list."""
        raw = getattr(obj, "evidence_urls", None) or ""
        urls = [u.strip() for u in raw.split(",") if u.strip()] if raw else []
        return cls(
            id=obj.id,
            driver_id=obj.driver_id,
            ride_id=obj.ride_id,
            incident_type=IncidentType(obj.incident_type),
            severity=IncidentSeverity(obj.severity),
            status=IncidentStatus(obj.status),
            description=obj.description,
            evidence_urls=urls,
            admin_note=obj.admin_note,
            reviewed_by_id=obj.reviewed_by_id,
            reviewed_at=obj.reviewed_at,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class DriverIncidentListOut(BaseModel):
    incidents: list[DriverIncidentResponse]
    total: int


class AdminIncidentRow(DriverIncidentResponse):
    """Admin view: identical to driver view for now; can extend with driver name."""

    driver_name: Optional[str] = None


class AdminIncidentListOut(BaseModel):
    incidents: list[AdminIncidentRow]
    total: int


class AdminIncidentSummary(BaseModel):
    """Platform-wide incident statistics for the admin dashboard."""

    total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_type: dict[str, int]
    open_count: int  # submitted + under_review
    critical_open: int  # critical severity + open
