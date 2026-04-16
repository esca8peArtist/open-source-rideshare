"""Corporate Fleet Fuel & Mileage Tracking models.

Fleet managers and drivers log fuel fill-ups and odometer readings for
company vehicles.  Over time the logs build up a complete fuel-cost and
mileage history that powers efficiency analytics (MPG / cost-per-mile).

Models:
  CorporateFleetFuelLog
      — one record per fuel fill-up or energy charge event.

Tables:
  corporate_fleet_fuel_logs
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


class FleetFuelType(str, PyEnum):
    """Fuel or energy type used to fill/charge the vehicle."""

    gasoline = "gasoline"
    diesel = "diesel"
    electric = "electric"
    hybrid = "hybrid"
    hydrogen = "hydrogen"
    other = "other"


class CorporateFleetFuelLog(Base):
    """A fuel fill-up or energy charge event for a corporate fleet vehicle.

    Fleet managers or drivers create one record per fill-up.  Odometer
    readings are optional but, when provided for consecutive records,
    enable MPG / cost-per-mile analytics.

    Attributes:
        id: UUID primary key.
        fleet_vehicle_id: FK to corporate_fleet_vehicles.id (CASCADE delete).
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        fuel_type: Category of fuel or energy (gasoline/diesel/electric/…).
        fill_date: Calendar date of the fill-up or charge.
        odometer_miles: Vehicle odometer reading at fill time, nullable.
        gallons_added: Fuel volume in gallons, nullable (use kwh_added for EVs).
        kwh_added: Energy added in kWh, nullable (for electric vehicles).
        cost_per_unit_usd: Price per gallon or per kWh at time of fill, nullable.
        total_cost_usd: Total amount paid at the pump/charger, nullable.
        station_name: Name or address of the fuel station or charging point, nullable.
        notes: Free-text notes, nullable.
        logged_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_fuel_logs"
    __table_args__ = (
        Index("ix_fleet_fuel_log_account_id", "account_id"),
        Index("ix_fleet_fuel_log_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_fuel_log_fill_date", "fill_date"),
        Index("ix_fleet_fuel_log_fuel_type", "fuel_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    fleet_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    fuel_type: Mapped[FleetFuelType] = mapped_column(
        Enum(FleetFuelType, name="fleetfueltype"),
        nullable=False,
    )

    fill_date: Mapped[date] = mapped_column(Date, nullable=False)

    odometer_miles: Mapped[int | None] = mapped_column(Integer, nullable=True)

    gallons_added: Mapped[float | None] = mapped_column(
        Numeric(precision=8, scale=3), nullable=True
    )

    kwh_added: Mapped[float | None] = mapped_column(
        Numeric(precision=8, scale=3), nullable=True
    )

    cost_per_unit_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=8, scale=4), nullable=True
    )

    total_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    station_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    logged_by_id: Mapped[int | None] = mapped_column(
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

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    logged_by = relationship(
        "User", foreign_keys=[logged_by_id], lazy="raise"
    )
