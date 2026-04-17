"""Corporate Fleet Driver Assignment models.

Fleet admins assign corporate account members to fleet vehicles, tracking
who is the primary, secondary, pool, or temporary driver of each vehicle
and recording the full assignment history.

Models:
  CorporateFleetDriverAssignment
      — one record per driver-vehicle assignment (current or historical).

Tables:
  corporate_fleet_driver_assignments
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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class FleetDriverAssignmentType(str, PyEnum):
    """Role of the driver within a fleet vehicle assignment."""

    primary = "primary"
    secondary = "secondary"
    pool = "pool"
    temporary = "temporary"


class FleetDriverAssignmentStatus(str, PyEnum):
    """Lifecycle status of a driver assignment."""

    active = "active"
    inactive = "inactive"
    pending = "pending"
    suspended = "suspended"


class CorporateFleetDriverAssignment(Base):
    """A driver assignment linking a user to a corporate fleet vehicle.

    Fleet admins create assignments that designate a user as the primary,
    secondary, pool, or temporary driver of a vehicle.  Business rules
    enforce that only one active primary driver exists per vehicle at any
    given time, and at most two active secondary drivers.

    Attributes:
        id: UUID primary key.
        vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        user_id: FK to users (CASCADE delete) — the driver being assigned, not null.
        assignment_type: Role classification (primary, secondary, pool, temporary).
        status: Lifecycle status (active, inactive, pending, suspended).
        start_date: Date the assignment becomes effective, not null.
        end_date: Date the assignment ends; null means indefinite, nullable.
        authorized_by_user_id: FK to users (SET NULL) — who authorized the assignment, nullable.
        notes: Free-text notes, nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_driver_assignments"
    __table_args__ = (
        Index("ix_fleet_driver_assignment_vehicle_id", "vehicle_id"),
        Index("ix_fleet_driver_assignment_account_id", "account_id"),
        Index("ix_fleet_driver_assignment_user_id", "user_id"),
        Index("ix_fleet_driver_assignment_status", "status"),
        Index("ix_fleet_driver_assignment_type", "assignment_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    assignment_type: Mapped[FleetDriverAssignmentType] = mapped_column(
        Enum(FleetDriverAssignmentType, name="fleetdriverassignmenttype"),
        nullable=False,
    )

    status: Mapped[FleetDriverAssignmentStatus] = mapped_column(
        Enum(FleetDriverAssignmentStatus, name="fleetdriverassignmentstatus"),
        nullable=False,
        default=FleetDriverAssignmentStatus.active,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    authorized_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        "CorporateFleetVehicle", foreign_keys=[vehicle_id], lazy="raise"
    )

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    user = relationship(
        "User", foreign_keys=[user_id], lazy="raise"
    )

    authorized_by = relationship(
        "User", foreign_keys=[authorized_by_user_id], lazy="raise"
    )
