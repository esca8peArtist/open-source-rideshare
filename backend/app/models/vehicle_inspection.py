"""Vehicle inspection record models.

Two tables:
  vehicle_inspections       — inspection records submitted by drivers
  vehicle_inspection_alerts — records of expiry/failure alert notifications
"""

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class InspectionType(str, enum.Enum):
    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"
    PRE_TRIP = "pre_trip"
    POST_TRIP = "post_trip"
    REPAIR_FOLLOWUP = "repair_followup"


class InspectionStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InspectionAlertType(str, enum.Enum):
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    FAILED = "failed"


class VehicleInspection(Base):
    """Vehicle inspection record submitted by a driver for platform compliance."""

    __tablename__ = "vehicle_inspections"

    __table_args__ = (
        Index("ix_vehicle_inspection_driver_status", "driver_id", "status"),
        Index("ix_vehicle_inspection_status_expiry", "status", "expiry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    inspection_type: Mapped[InspectionType] = mapped_column(
        Enum(InspectionType), nullable=False
    )
    inspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[InspectionStatus] = mapped_column(
        Enum(InspectionStatus),
        default=InspectionStatus.PENDING_REVIEW,
        nullable=False,
        index=True,
    )

    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    odometer_reading: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    failed_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
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

    driver = relationship("User", foreign_keys=[driver_id], backref="vehicle_inspections")
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    alerts = relationship(
        "VehicleInspectionAlert", back_populates="inspection", cascade="all, delete-orphan"
    )


class VehicleInspectionAlert(Base):
    """Record of an expiry or failure alert notification for a vehicle inspection."""

    __tablename__ = "vehicle_inspection_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_inspections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type: Mapped[InspectionAlertType] = mapped_column(
        Enum(InspectionAlertType), nullable=False
    )
    alert_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    inspection = relationship("VehicleInspection", back_populates="alerts")
