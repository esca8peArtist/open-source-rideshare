"""Pydantic schemas for accessibility and WAV endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.accessibility import WAVCertificationStatus


# ---------------------------------------------------------------------------
# Rider accessibility schemas
# ---------------------------------------------------------------------------


class RiderAccessibilityProfileUpdate(BaseModel):
    """Fields the rider can set on their accessibility profile."""

    needs_wav: bool = False
    has_mobility_device: bool = False
    visual_impairment: bool = False
    hearing_impairment: bool = False
    other_needs: str | None = Field(default=None, max_length=1000)


class RiderAccessibilityProfileResponse(BaseModel):
    """Full accessibility profile returned to the rider."""

    id: int
    rider_id: int
    needs_wav: bool
    has_mobility_device: bool
    visual_impairment: bool
    hearing_impairment: bool
    other_needs: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Driver WAV schemas
# ---------------------------------------------------------------------------


class DriverWAVCertificationSubmit(BaseModel):
    """Fields the driver provides when submitting or updating a WAV cert."""

    vehicle_make: str | None = Field(default=None, max_length=100)
    vehicle_model: str | None = Field(default=None, max_length=100)
    vehicle_year: int | None = Field(default=None, ge=1990, le=2030)
    certification_document_url: str | None = Field(default=None, max_length=500)
    certification_number: str | None = Field(default=None, max_length=100)
    expires_at: datetime | None = None


class DriverWAVCertificationResponse(BaseModel):
    """WAV certification record returned to driver or admin."""

    id: int
    driver_id: int
    status: WAVCertificationStatus
    vehicle_make: str | None
    vehicle_model: str | None
    vehicle_year: int | None
    certification_document_url: str | None
    certification_number: str | None
    submitted_at: datetime
    verified_at: datetime | None
    expires_at: datetime | None
    verified_by_admin_id: int | None
    admin_note: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin verification schema
# ---------------------------------------------------------------------------


class AdminWAVVerifyRequest(BaseModel):
    """Admin decision on a pending WAV certification."""

    approve: bool
    admin_note: str | None = Field(default=None, max_length=1000)
    # If approving, admin may set / override the expiry date.
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Admin stats schema
# ---------------------------------------------------------------------------


class WAVPlatformStats(BaseModel):
    """Aggregate WAV coverage statistics for the admin dashboard."""

    total_riders_needing_wav: int
    drivers_pending_wav: int
    drivers_verified_wav: int
    drivers_rejected_wav: int
    drivers_expired_wav: int
    # Fraction of WAV-requesting riders that could theoretically be served
    # (verified WAV drivers / riders needing WAV, capped at 1.0).
    coverage_ratio: float
