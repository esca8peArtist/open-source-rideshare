"""Corporate Fleet Vehicle models.

Enterprise corporate accounts can define a pool of company-owned or leased
vehicles and assign drivers to them.

Models:
  CorporateFleetVehicle
      — one record per vehicle in the corporate fleet.
  CorporateFleetAssignment
      — tracks which driver is currently assigned (or was assigned) to a vehicle.

Tables:
  corporate_fleet_vehicles
  corporate_fleet_assignments
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateFleetVehicle(Base):
    """A company-owned or leased vehicle in a corporate fleet.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        name: Human-readable label, e.g. "Executive Sedan 1".
        vehicle_type: Category string — sedan/suv/van/minivan/truck/other.
        make: Manufacturer name, e.g. "Toyota".
        model_name: Model name, e.g. "Camry". Named model_name to avoid
            SQLAlchemy conflict with the built-in model attribute.
        year: Model year, e.g. 2024.
        license_plate: License plate number.
        color: Vehicle colour, e.g. "Black".
        capacity: Passenger capacity (default 4).
        is_wav: Whether the vehicle is wheelchair-accessible (default False).
        notes: Free-text notes for fleet managers.
        is_active: Whether the vehicle is currently available.
        created_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_vehicles"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "name", name="uq_corp_fleet_vehicle_account_name"
        ),
        Index("ix_corp_fleet_vehicle_account_id", "account_id"),
        Index("ix_corp_fleet_vehicle_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    make: Mapped[str | None] = mapped_column(String(50), nullable=True)

    model_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    license_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)

    color: Mapped[str | None] = mapped_column(String(30), nullable=True)

    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    is_wav: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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

    created_by = relationship(
        "User", foreign_keys=[created_by_id], lazy="raise"
    )

    assignments = relationship(
        "CorporateFleetAssignment",
        back_populates="vehicle",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateFleetAssignment(Base):
    """Assignment of a driver to a corporate fleet vehicle.

    Tracks the full assignment history.  Only one assignment per vehicle may
    be active at a time; ``assign_driver`` deactivates any prior active record
    before creating a new one.

    Attributes:
        id: UUID primary key.
        fleet_vehicle_id: FK to corporate_fleet_vehicles.id (CASCADE delete).
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        driver_profile_id: FK to driver_profiles.id (SET NULL), nullable.
        assigned_by_id: FK to users.id (SET NULL), nullable.
        is_active: Whether this assignment is current.
        notes: Free-text notes on the assignment.
        created_at: UTC timestamp when the assignment was created.
    """

    __tablename__ = "corporate_fleet_assignments"
    __table_args__ = (
        Index("ix_corp_fleet_assignment_vehicle_id", "fleet_vehicle_id"),
        Index("ix_corp_fleet_assignment_driver_id", "driver_profile_id"),
        Index("ix_corp_fleet_assignment_is_active", "is_active"),
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

    driver_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    vehicle = relationship(
        "CorporateFleetVehicle", back_populates="assignments", lazy="raise"
    )

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
