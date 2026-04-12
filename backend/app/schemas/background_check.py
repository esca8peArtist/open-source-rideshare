"""Pydantic schemas for background check API."""

from datetime import datetime

from pydantic import BaseModel, Field


class OrderBackgroundCheckRequest(BaseModel):
    """Driver request to order a background check."""

    package: str = Field(
        default="driver_pro",
        description="Checkr package: driver_pro, motor_vehicle_report, or basic",
    )

    def validate_package(self) -> bool:
        return self.package in {"driver_pro", "motor_vehicle_report", "basic"}


class BackgroundCheckResponse(BaseModel):
    """Public-facing background check status (safe for driver to see)."""

    id: int
    driver_profile_id: int
    package: str
    status: str
    report_url: str | None
    ordered_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminBackgroundCheckResponse(BaseModel):
    """Full background check detail for admin."""

    id: int
    driver_profile_id: int
    checkr_candidate_id: str | None
    checkr_check_id: str | None
    package: str
    status: str
    report_url: str | None
    admin_override_reason: str | None
    overridden_by: int | None
    ordered_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminOverrideRequest(BaseModel):
    """Admin override of a background check result."""

    status: str = Field(
        ...,
        description="New status: clear, consider, or cancelled",
    )
    reason: str = Field(..., min_length=1, description="Required reason for override")


class AdminBackgroundCheckListResponse(BaseModel):
    checks: list[AdminBackgroundCheckResponse]
    total: int
