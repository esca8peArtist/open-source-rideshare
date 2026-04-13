"""Driver license and vehicle registration document models.

Four tables:
  driver_licenses               — driver's license records submitted by drivers
  driver_license_alerts         — records of expiry alert notifications sent
  vehicle_registrations         — vehicle registration records submitted by drivers
  vehicle_registration_alerts   — records of expiry alert notifications sent
"""

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class LicenseClass(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    CDL = "CDL"


class DocumentStatus(str, enum.Enum):
    PENDING_UPLOAD = "pending_upload"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DocumentAlertType(str, enum.Enum):
    THIRTY_DAY = "30_day"
    SEVEN_DAY = "7_day"
    ONE_DAY = "1_day"
    EXPIRED = "expired"


class DriverLicense(Base):
    """Driver's license document submitted by a driver for platform compliance."""

    __tablename__ = "driver_licenses"

    __table_args__ = (
        Index("ix_driver_license_driver_status", "driver_id", "status"),
        Index("ix_driver_license_status_expiry", "status", "expiry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    license_number: Mapped[str] = mapped_column(String(100), nullable=False)
    state_issued: Mapped[str] = mapped_column(String(50), nullable=False)
    license_class: Mapped[LicenseClass] = mapped_column(
        Enum(LicenseClass), nullable=False
    )
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Stored file URL — optional until driver uploads it
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="licensedocumentstatus"),
        default=DocumentStatus.PENDING_UPLOAD,
        nullable=False,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    uploaded_at: Mapped[datetime | None] = mapped_column(
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

    driver = relationship("User", foreign_keys=[driver_id], backref="driver_licenses")
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    alerts = relationship(
        "DriverLicenseAlert", back_populates="license", cascade="all, delete-orphan"
    )


class DriverLicenseAlert(Base):
    """Record of an expiry alert notification that was sent to a driver for their license."""

    __tablename__ = "driver_license_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    license_id: Mapped[int] = mapped_column(
        ForeignKey("driver_licenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type: Mapped[DocumentAlertType] = mapped_column(
        Enum(DocumentAlertType, name="licensealerttype"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    driver = relationship("User", foreign_keys=[driver_id])
    license = relationship("DriverLicense", back_populates="alerts")


class VehicleRegistration(Base):
    """Vehicle registration document submitted by a driver for platform compliance."""

    __tablename__ = "vehicle_registrations"

    __table_args__ = (
        Index("ix_vehicle_registration_driver_status", "driver_id", "status"),
        Index("ix_vehicle_registration_status_expiry", "status", "expiry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Vehicle identifier — stored as a string to avoid hard dependency on the
    # driver_vehicles table schema which may evolve independently.
    vehicle_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    plate_number: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Stored file URL — optional until driver uploads it
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="registrationdocumentstatus"),
        default=DocumentStatus.PENDING_UPLOAD,
        nullable=False,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    uploaded_at: Mapped[datetime | None] = mapped_column(
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

    driver = relationship(
        "User", foreign_keys=[driver_id], backref="vehicle_registrations"
    )
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    alerts = relationship(
        "VehicleRegistrationAlert",
        back_populates="registration",
        cascade="all, delete-orphan",
    )


class VehicleRegistrationAlert(Base):
    """Record of an expiry alert notification sent to a driver for their vehicle registration."""

    __tablename__ = "vehicle_registration_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type: Mapped[DocumentAlertType] = mapped_column(
        Enum(DocumentAlertType, name="registrationalerttype"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    driver = relationship("User", foreign_keys=[driver_id])
    registration = relationship("VehicleRegistration", back_populates="alerts")
