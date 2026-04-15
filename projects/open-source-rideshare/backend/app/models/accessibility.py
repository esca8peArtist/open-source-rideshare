"""Accessibility and Wheelchair Accessible Vehicle (WAV) models.

Rideshare platforms in many jurisdictions (ADA, TfL, etc.) must provide
accessible rides to riders with disabilities. This module tracks:

  1. RiderAccessibilityProfile — rider self-reported accessibility needs
     (WAV required, mobility device, visual/hearing impairment, etc.)

  2. DriverWAVCertification — driver / vehicle WAV capability, verified
     by admin before inclusion in the accessible dispatch pool.

Tables
------
rider_accessibility_profiles   — one row per rider (created lazily)
driver_wav_certifications      — one row per driver (upserted on submission)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WAVCertificationStatus(str, enum.Enum):
    pending = "pending"       # driver submitted; awaiting admin review
    verified = "verified"     # admin confirmed WAV capability
    rejected = "rejected"     # admin rejected (failed inspection / docs)
    expired = "expired"       # certification period lapsed


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RiderAccessibilityProfile(Base):
    """Self-reported accessibility needs for a rider.

    Created lazily on the rider's first GET or PUT request so there is no
    need for a signup-time prompt.  All flag fields default to False so an
    empty profile is valid and non-intrusive.
    """

    __tablename__ = "rider_accessibility_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)

    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # WAV — rider requires a wheelchair-accessible vehicle.
    needs_wav: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Mobility device — cane, walker, non-folding scooter, etc. (doesn't
    # necessarily require a full WAV but driver should be informed).
    has_mobility_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Sensory impairments — informational flags for the driver app.
    visual_impairment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hearing_impairment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Free-text for anything not covered by the flags above.
    other_needs: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    rider = relationship("User", foreign_keys=[rider_id], backref="accessibility_profile")


class DriverWAVCertification(Base):
    """WAV capability record for a driver.

    Drivers self-submit with documentation; admin verifies before the driver
    is included in the WAV dispatch pool.  One row per driver (upserted).
    """

    __tablename__ = "driver_wav_certifications"

    id: Mapped[int] = mapped_column(primary_key=True)

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[WAVCertificationStatus] = mapped_column(
        SAEnum(WAVCertificationStatus),
        nullable=False,
        default=WAVCertificationStatus.pending,
    )

    # Vehicle details submitted by driver.
    vehicle_make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vehicle_year: Mapped[int | None] = mapped_column(nullable=True)

    # External certification / inspection document reference.
    certification_document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Optional official cert number (e.g. from a local transit authority).
    certification_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Dates
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Admin who verified (nullable — not set until verified/rejected).
    verified_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Admin note on verification decision.
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("User", foreign_keys=[driver_id], backref="wav_certification")
    verified_by = relationship("User", foreign_keys=[verified_by_admin_id])
