import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DocumentType(str, enum.Enum):
    DRIVERS_LICENSE = "drivers_license"
    VEHICLE_REGISTRATION = "vehicle_registration"
    INSURANCE = "insurance"
    BACKGROUND_CHECK = "background_check"
    VEHICLE_INSPECTION = "vehicle_inspection"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DriverDocument(Base):
    __tablename__ = "driver_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(ForeignKey("driver_profiles.id"), index=True)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType))
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus), default=VerificationStatus.PENDING
    )

    # Document reference (file path, S3 key, or external ID)
    document_ref: Mapped[str] = mapped_column(String(500))
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Review fields
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    driver_profile = relationship("DriverProfile", backref="documents")
    reviewer = relationship("User", foreign_keys=[reviewed_by])
