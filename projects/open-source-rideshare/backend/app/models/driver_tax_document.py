"""Driver tax document models.

Tracks IRS tax reporting for driver 1099-NEC and earnings summary documents.

DriverTaxProfile — stores W-9 info (TIN last 4 only, never full TIN) per driver.
DriverTaxDocument — annual tax document generated for each driver per year.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class TinType(str, enum.Enum):
    ssn = "ssn"
    ein = "ein"


class TaxDocumentType(str, enum.Enum):
    nec_1099 = "1099_nec"
    earnings_summary = "earnings_summary"


class TaxDocumentStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    submitted_to_irs = "submitted_to_irs"
    corrected = "corrected"


class DriverTaxProfile(Base):
    """W-9 / taxpayer identification profile for a driver.

    Only the last 4 digits of the TIN are stored.  The full TIN must never
    be persisted in the platform database.
    """

    __tablename__ = "driver_tax_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), unique=True, index=True
    )

    tin_type: Mapped[TinType | None] = mapped_column(SAEnum(TinType), nullable=True)
    # Store ONLY the last 4 digits — never the full TIN.
    tin_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    has_w9: Mapped[bool] = mapped_column(Boolean, default=False)
    w9_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_backup_withholding_exempt: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    driver_profile = relationship("DriverProfile", backref="tax_profile")


class DriverTaxDocument(Base):
    """Annual tax document generated for a driver.

    For drivers whose gross earnings are $600 or more in a calendar year a
    1099-NEC document is generated.  Below that threshold only an
    earnings_summary is produced.
    """

    __tablename__ = "driver_tax_documents"

    __table_args__ = (
        UniqueConstraint("driver_profile_id", "tax_year", "document_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[TaxDocumentType] = mapped_column(
        SAEnum(TaxDocumentType), nullable=False
    )
    status: Mapped[TaxDocumentStatus] = mapped_column(
        SAEnum(TaxDocumentStatus), nullable=False, default=TaxDocumentStatus.pending
    )

    # Monetary values stored as integer cents to avoid floating-point issues.
    gross_earnings_cents: Mapped[int] = mapped_column(Integer, default=0)
    nonemployee_compensation_cents: Mapped[int] = mapped_column(Integer, default=0)
    rides_count: Mapped[int] = mapped_column(Integer, default=0)

    admin_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    driver_profile = relationship("DriverProfile", backref="tax_documents")
