"""Corporate Fleet Vehicle Acquisition and Disposal models.

Fleet managers record how vehicles joined the fleet (purchased, leased,
financed, donated) and how they left it (sold, scrapped, lease returned, etc.).

Models:
  CorporateFleetVehicleAcquisition
      — one active acquisition record per fleet vehicle (financial terms).
  CorporateFleetVehicleDisposal
      — one disposal record per retired fleet vehicle.

Tables:
  corporate_fleet_vehicle_acquisitions
  corporate_fleet_vehicle_disposals
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
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AcquisitionType(str, PyEnum):
    """How the fleet vehicle was acquired."""

    purchased = "purchased"
    leased = "leased"
    financed = "financed"
    donated = "donated"
    other = "other"


class DisposalReason(str, PyEnum):
    """Why the fleet vehicle is being retired from service."""

    sold = "sold"
    traded_in = "traded_in"
    scrapped = "scrapped"
    donated = "donated"
    lease_returned = "lease_returned"
    stolen_written_off = "stolen_written_off"
    other = "other"


class CorporateFleetVehicleAcquisition(Base):
    """Financial acquisition record for a corporate fleet vehicle.

    Tracks how a vehicle entered the fleet — outright purchase, lease,
    financed loan, or donation — along with the associated financial terms.
    Only one record per vehicle may have ``is_active=True`` at any time;
    this invariant is enforced at the service layer.

    Attributes:
        id: UUID primary key.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete).
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        acquisition_type: How the vehicle was acquired (AcquisitionType enum).
        vendor_name: Seller, lessor, or donor name, nullable.
        acquisition_date: Date the vehicle was acquired.
        acquisition_cost_usd: Total purchase price in USD, nullable.
        lease_start_date: First day of the lease term, nullable.
        lease_end_date: Last day of the lease term, nullable.
        monthly_lease_payment_usd: Monthly lease payment in USD, nullable.
        lease_mileage_allowance_annual: Annual mileage limit under the lease, nullable.
        financed_amount_usd: Principal amount financed in USD, nullable.
        loan_term_months: Number of months in the loan term, nullable.
        monthly_loan_payment_usd: Monthly loan payment in USD, nullable.
        notes: Free-text notes, nullable.
        is_active: True for the current active acquisition record.
        created_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_vehicle_acquisitions"
    __table_args__ = (
        Index("ix_fleet_acquisition_account_id", "account_id"),
        Index("ix_fleet_acquisition_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_acquisition_type", "acquisition_type"),
        Index("ix_fleet_acquisition_is_active", "is_active"),
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

    acquisition_type: Mapped[AcquisitionType] = mapped_column(
        Enum(AcquisitionType, name="acquisitiontype"),
        nullable=False,
    )

    vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)

    acquisition_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )

    lease_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    lease_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    monthly_lease_payment_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    lease_mileage_allowance_annual: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    financed_amount_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )

    loan_term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    monthly_loan_payment_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

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

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    created_by = relationship(
        "User", foreign_keys=[created_by_id], lazy="raise"
    )


class CorporateFleetVehicleDisposal(Base):
    """Disposal record for a retired corporate fleet vehicle.

    When a vehicle is permanently removed from the fleet — sold, scrapped,
    returned at lease end, donated, or written off — a disposal record is
    created and the vehicle's ``is_active`` flag is set to ``False``.
    Only one disposal record may exist per vehicle.

    Attributes:
        id: UUID primary key.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete).
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        disposal_reason: Why the vehicle left the fleet (DisposalReason enum).
        disposal_date: Date the vehicle was disposed of.
        sale_price_usd: Sale or trade-in value received in USD, nullable.
        buyer_name: Name of the buyer or receiving party, nullable.
        notes: Free-text notes, nullable.
        disposed_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
    """

    __tablename__ = "corporate_fleet_vehicle_disposals"
    __table_args__ = (
        Index("ix_fleet_disposal_account_id", "account_id"),
        Index("ix_fleet_disposal_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_disposal_reason", "disposal_reason"),
        Index("ix_fleet_disposal_date", "disposal_date"),
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

    disposal_reason: Mapped[DisposalReason] = mapped_column(
        Enum(DisposalReason, name="disposalreason"),
        nullable=False,
    )

    disposal_date: Mapped[date] = mapped_column(Date, nullable=False)

    sale_price_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )

    buyer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    disposed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    disposed_by = relationship(
        "User", foreign_keys=[disposed_by_id], lazy="raise"
    )
