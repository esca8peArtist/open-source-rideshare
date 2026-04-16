"""Corporate Vehicle Maintenance Log models.

Fleet managers track service history for company vehicles — oil changes,
inspections, tire rotations, brake services, and other maintenance events.
Each record supports scheduled (future) and completed (historical) entries
with optional next-due date/odometer alerts.

Models:
  CorporateVehicleMaintenanceLog
      — one record per maintenance event or scheduled service.

Tables:
  corporate_vehicle_maintenance_logs
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
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


class MaintenanceType(str, PyEnum):
    """Category of vehicle maintenance performed."""

    oil_change = "oil_change"
    tire_rotation = "tire_rotation"
    brake_service = "brake_service"
    inspection = "inspection"
    battery = "battery"
    fluid_check = "fluid_check"
    filter_change = "filter_change"
    wiper_replacement = "wiper_replacement"
    other = "other"


class CorporateVehicleMaintenanceLog(Base):
    """A maintenance event (scheduled or completed) for a corporate fleet vehicle.

    Admins create records for upcoming services (with scheduled_date) and
    later mark them complete (filling completed_at, cost, odometer, vendor).
    ``next_due_date`` and ``next_due_odometer`` carry forward-looking reminders
    so managers can see what comes due for each vehicle.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        maintenance_type: Category enum value.
        title: Short human-readable label, e.g. "60k-mile oil change".
        description: Optional detailed notes about the service.
        scheduled_date: When the service is planned (timezone-aware), nullable.
        completed_at: When the service was completed (timezone-aware), nullable.
        odometer_miles: Vehicle mileage at time of service, nullable.
        cost_usd: Total cost for the service, nullable.
        vendor_name: Name of the service centre / vendor, nullable.
        notes: Free-text field for additional context, nullable.
        is_completed: True when the service has been performed.
        next_due_date: Next service due date (timezone-aware), nullable.
        next_due_odometer: Next service due mileage, nullable.
        created_by_id: FK to users.id (SET NULL), nullable.
        completed_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_vehicle_maintenance_logs"
    __table_args__ = (
        Index("ix_veh_maint_log_account_id", "account_id"),
        Index("ix_veh_maint_log_vehicle_id", "fleet_vehicle_id"),
        Index("ix_veh_maint_log_scheduled_date", "scheduled_date"),
        Index("ix_veh_maint_log_next_due_date", "next_due_date"),
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

    maintenance_type: Mapped[MaintenanceType] = mapped_column(
        Enum(MaintenanceType, name="maintenancetype"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    scheduled_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    odometer_miles: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cost_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    next_due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    next_due_odometer: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    completed_by_id: Mapped[int | None] = mapped_column(
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

    completed_by = relationship(
        "User", foreign_keys=[completed_by_id], lazy="raise"
    )
