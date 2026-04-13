"""Driver insurance document models.

Two tables:
  driver_insurance_documents — insurance policy records submitted by drivers
  insurance_expiry_alerts    — records of expiry alert notifications sent
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class InsuranceDocumentType(str, enum.Enum):
    LIABILITY = "liability"
    COMPREHENSIVE = "comprehensive"
    COMMERCIAL = "commercial"
    PERSONAL_INJURY_PROTECTION = "personal_injury_protection"


class InsuranceDocumentStatus(str, enum.Enum):
    PENDING_UPLOAD = "pending_upload"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InsuranceAlertType(str, enum.Enum):
    THIRTY_DAY = "30_day"
    SEVEN_DAY = "7_day"
    ONE_DAY = "1_day"
    EXPIRED = "expired"


class DriverInsuranceDocument(Base):
    """Insurance policy document submitted by a driver for platform compliance."""

    __tablename__ = "driver_insurance_documents"

    __table_args__ = (
        Index("ix_driver_insurance_status_expiry", "status", "policy_end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    document_type: Mapped[InsuranceDocumentType] = mapped_column(
        Enum(InsuranceDocumentType), nullable=False
    )
    insurance_provider: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_number: Mapped[str] = mapped_column(String(100), nullable=False)
    coverage_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    policy_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    policy_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Stored file URL — optional until admin reviews
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[InsuranceDocumentStatus] = mapped_column(
        Enum(InsuranceDocumentStatus),
        default=InsuranceDocumentStatus.PENDING_UPLOAD,
        nullable=False,
        index=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("User", foreign_keys=[driver_id], backref="insurance_documents")
    verifier = relationship("User", foreign_keys=[verified_by])
    expiry_alerts = relationship(
        "InsuranceExpiryAlert", back_populates="document", cascade="all, delete-orphan"
    )


class InsuranceExpiryAlert(Base):
    """Record of an expiry alert notification that was sent to a driver."""

    __tablename__ = "insurance_expiry_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("driver_insurance_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type: Mapped[InsuranceAlertType] = mapped_column(
        Enum(InsuranceAlertType), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    driver = relationship("User", foreign_keys=[driver_id])
    document = relationship("DriverInsuranceDocument", back_populates="expiry_alerts")
