"""Corporate Fleet Maintenance Scheduling models.

Fleet managers schedule preventive maintenance and log completed service
records for company vehicles.  Both scheduled upcoming work and completed
service history are tracked in a single table with a status field.

Models:
  CorporateFleetMaintenanceRecord
      — one record per scheduled or completed maintenance event.

Tables:
  corporate_fleet_maintenance_records
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class FleetMaintenanceType(str, PyEnum):
    """Type of preventive or corrective maintenance service."""

    oil_change = "oil_change"
    tire_rotation = "tire_rotation"
    brake_inspection = "brake_inspection"
    air_filter = "air_filter"
    transmission_service = "transmission_service"
    battery_replacement = "battery_replacement"
    coolant_flush = "coolant_flush"
    spark_plugs = "spark_plugs"
    wheel_alignment = "wheel_alignment"
    state_inspection = "state_inspection"
    recall_repair = "recall_repair"
    other = "other"


class FleetMaintenanceStatus(str, PyEnum):
    """Lifecycle status of a maintenance record."""

    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"
    overdue = "overdue"


class CorporateFleetMaintenanceRecord(Base):
    """A scheduled or completed maintenance record for a corporate fleet vehicle.

    Fleet admins schedule upcoming maintenance and mark records complete
    once service is performed.  Each record captures the service type,
    vendor, cost, odometer readings, and next-service thresholds so fleet
    managers can anticipate upcoming work.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        maintenance_type: Type of maintenance service performed.
        status: Lifecycle status (scheduled, in_progress, completed, cancelled, overdue).
        scheduled_date: Date the service is scheduled for, nullable.
        completed_date: Date the service was completed, nullable.
        odometer_at_service: Odometer reading at time of service (miles), nullable.
        next_service_odometer: Odometer reading at which the next service is due, nullable.
        next_service_date: Date the next service of this type is due, nullable.
        cost_usd: Total service cost in USD, nullable.
        vendor_name: Service vendor or shop name, nullable (1–200 chars).
        technician_name: Technician who performed the service, nullable (1–200 chars).
        description: Short description of the work performed, nullable (1–500 chars).
        notes: Free-text notes, nullable.
        created_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_maintenance_records"
    __table_args__ = (
        Index("ix_fleet_maintenance_account_id", "account_id"),
        Index("ix_fleet_maintenance_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_maintenance_status", "status"),
        Index("ix_fleet_maintenance_type", "maintenance_type"),
        Index("ix_fleet_maintenance_scheduled_date", "scheduled_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    fleet_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )

    maintenance_type: Mapped[FleetMaintenanceType] = mapped_column(
        Enum(FleetMaintenanceType, name="fleetmaintenancetype"),
        nullable=False,
    )

    status: Mapped[FleetMaintenanceStatus] = mapped_column(
        Enum(FleetMaintenanceStatus, name="fleetmaintenancestatus"),
        nullable=False,
        default=FleetMaintenanceStatus.scheduled,
    )

    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    odometer_at_service: Mapped[int | None] = mapped_column(Integer, nullable=True)

    next_service_odometer: Mapped[int | None] = mapped_column(Integer, nullable=True)

    next_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    cost_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    technician_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    created_by = relationship(
        "User", foreign_keys=[created_by_id], lazy="raise"
    )
