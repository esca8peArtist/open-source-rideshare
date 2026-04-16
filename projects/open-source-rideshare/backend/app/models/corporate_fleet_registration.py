"""Corporate Fleet Vehicle Registration models.

Fleet managers track state/jurisdiction registration records for company
vehicles — registration numbers, expiration dates, and annual fees —
with expiry date alerts.

Models:
  CorporateFleetVehicleRegistration
      — one record per registration attached to a fleet vehicle.

Tables:
  corporate_fleet_vehicle_registrations
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
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


class CorporateFleetVehicleRegistration(Base):
    """A vehicle registration record for a corporate fleet vehicle.

    Admins create records linking registration documents to fleet vehicles,
    tracking registration numbers, state/jurisdiction, expiration dates, and
    annual fees.  Expiry date alerts allow fleet managers to renew registrations
    before lapse.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        registration_number: DMV registration document number, unique per account.
        registration_state: State or jurisdiction (e.g. "California", "New York").
        registration_date: Date when the vehicle was registered.
        expiration_date: Date when the registration expires.
        annual_fee_usd: Annual registration fee in USD, nullable.
        registered_owner_name: Legal owner name on title, nullable.
        is_active: True when the registration record is currently active.
        notes: Free-text notes, nullable.
        created_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_vehicle_registrations"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "registration_number",
            name="uq_fleet_registration_account_reg_number",
        ),
        Index("ix_fleet_registration_account_id", "account_id"),
        Index("ix_fleet_registration_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_registration_expiration_date", "expiration_date"),
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

    registration_number: Mapped[str] = mapped_column(String(100), nullable=False)

    registration_state: Mapped[str] = mapped_column(String(100), nullable=False)

    registration_date: Mapped[date] = mapped_column(Date, nullable=False)

    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)

    annual_fee_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    registered_owner_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
