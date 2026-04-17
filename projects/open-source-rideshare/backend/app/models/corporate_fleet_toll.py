"""Corporate Fleet Toll & Transponder Management models.

Fleet managers track toll transponders (E-ZPass, FasTrak, SunPass, etc.)
assigned to company vehicles and log individual toll charges.  Over time
the charge records build a complete toll-cost history for analytics and
expense reporting.

Models:
  CorporateFleetTollTransponder
      — one record per transponder assigned to a fleet vehicle.
  CorporateFleetTollCharge
      — one record per individual toll charge event.

Tables:
  corporate_fleet_toll_transponders
  corporate_fleet_toll_charges
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class TransponderProvider(str, PyEnum):
    """Toll authority or transponder network."""

    ezpass = "ezpass"
    fastrak = "fastrak"
    sunpass = "sunpass"
    peach_pass = "peach_pass"
    ipass = "ipass"
    ktag = "ktag"
    pikepass = "pikepass"
    nc_quick_pass = "nc_quick_pass"
    other = "other"


class CorporateFleetTollTransponder(Base):
    """A toll transponder assigned to a corporate fleet vehicle.

    Fleet admins create one record per transponder.  A vehicle may have
    multiple transponders over time (e.g. when moving between providers or
    replacing a lost device), but typically only one is active at a time.
    Deactivating a transponder sets ``removed_date`` to today.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        transponder_number: Transponder device number, unique per account.
        provider: Toll authority / transponder network enum.
        assigned_date: Date the transponder was assigned to the vehicle.
        removed_date: Date the transponder was removed, nullable.
        monthly_plan_cost_usd: Fixed monthly plan fee in USD, nullable.
        toll_account_number: Toll authority account number, nullable.
        is_active: True while the transponder is active on this vehicle.
        notes: Free-text notes, nullable.
        assigned_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_toll_transponders"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "transponder_number",
            name="uq_fleet_toll_transponder_account_number",
        ),
        Index("ix_fleet_toll_transponder_account_id", "account_id"),
        Index("ix_fleet_toll_transponder_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_toll_transponder_is_active", "is_active"),
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

    transponder_number: Mapped[str] = mapped_column(String(100), nullable=False)

    provider: Mapped[TransponderProvider] = mapped_column(
        Enum(TransponderProvider, name="transponderprovider"),
        nullable=False,
    )

    assigned_date: Mapped[date] = mapped_column(Date, nullable=False)

    removed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    monthly_plan_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    toll_account_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_by_id: Mapped[int | None] = mapped_column(
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

    assigned_by = relationship(
        "User", foreign_keys=[assigned_by_id], lazy="raise"
    )


class CorporateFleetTollCharge(Base):
    """An individual toll charge for a corporate fleet vehicle.

    Fleet admins or drivers log one record per toll transaction.  The
    transponder field is optional so that charges can still be recorded
    even if the transponder record has been deactivated or deleted.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        transponder_id: FK to corporate_fleet_toll_transponders (SET NULL), nullable.
        charge_date: Date when the toll was charged.
        plaza_name: Name of the toll plaza or bridge, nullable.
        amount_usd: Toll amount in USD.
        entry_location: Entry point description, nullable.
        exit_location: Exit point description, nullable.
        trip_purpose: Business purpose for the trip, nullable.
        notes: Free-text notes, nullable.
        logged_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
    """

    __tablename__ = "corporate_fleet_toll_charges"
    __table_args__ = (
        Index("ix_fleet_toll_charge_account_id", "account_id"),
        Index("ix_fleet_toll_charge_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_toll_charge_date", "charge_date"),
        Index("ix_fleet_toll_charge_transponder_id", "transponder_id"),
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

    transponder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_fleet_toll_transponders.id", ondelete="SET NULL"),
        nullable=True,
    )

    charge_date: Mapped[date] = mapped_column(Date, nullable=False)

    plaza_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    amount_usd: Mapped[float] = mapped_column(
        Numeric(precision=8, scale=2), nullable=False
    )

    entry_location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    exit_location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    trip_purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    logged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    transponder = relationship(
        "CorporateFleetTollTransponder",
        foreign_keys=[transponder_id],
        lazy="raise",
    )

    logged_by = relationship(
        "User", foreign_keys=[logged_by_id], lazy="raise"
    )
