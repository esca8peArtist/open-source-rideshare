"""GDPR/CCPA Data Privacy Compliance models.

Cooperative rideshare platforms have a legal and ethical obligation to give
riders control over their data. This module covers:

  - PrivacyConsentRecord  — audit trail of what policies a user has accepted
  - DataExportRequest     — GDPR "right of access" / CCPA data download
  - AccountDeletionRequest — GDPR "right to erasure" / CCPA deletion request

Tables:
  privacy_consent_records     — per-user, per-policy consent history
  data_export_requests        — requested data exports with status lifecycle
  account_deletion_requests   — deletion requests with 30-day cool-off period
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PolicyType(str, enum.Enum):
    PRIVACY_POLICY = "PRIVACY_POLICY"
    TERMS_OF_SERVICE = "TERMS_OF_SERVICE"
    MARKETING = "MARKETING"
    DATA_SHARING = "DATA_SHARING"


class ExportStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    DOWNLOADED = "DOWNLOADED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class DeletionStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PrivacyConsentRecord(Base):
    """Audit record of a user's consent to a specific policy version.

    Unique per (user_id, policy_type, policy_version) — upserted on change.
    Stores the raw IP address and user-agent for legal evidence purposes.
    """

    __tablename__ = "privacy_consent_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "policy_type",
            "policy_version",
            name="uq_consent_user_policy_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    policy_type: Mapped[PolicyType] = mapped_column(
        SAEnum(PolicyType, name="policytype", create_type=True),
        nullable=False,
    )

    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)

    consented: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Legal evidence fields — nullable so older records without this data are ok
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataExportRequest(Base):
    """Tracks a user's GDPR/CCPA data export request through its lifecycle.

    Exports expire after 7 days once ready.  Download count is capped to
    prevent excessive access after the initial download.
    """

    __tablename__ = "data_export_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    status: Mapped[ExportStatus] = mapped_column(
        SAEnum(ExportStatus, name="exportstatus", create_type=True),
        nullable=False,
        default=ExportStatus.PENDING,
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class AccountDeletionRequest(Base):
    """Tracks a user's right-to-erasure / CCPA deletion request.

    A 30-day grace period is enforced between the request and execution, giving
    the user time to cancel.  Only one active (PENDING or CONFIRMED) request
    may exist per user at a time.
    """

    __tablename__ = "account_deletion_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    status: Mapped[DeletionStatus] = mapped_column(
        SAEnum(DeletionStatus, name="deletionstatus", create_type=True),
        nullable=False,
        default=DeletionStatus.PENDING,
    )

    # Optional reason provided by the user
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Execution is scheduled 30 days after the request
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
