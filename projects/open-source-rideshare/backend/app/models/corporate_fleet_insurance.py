"""Corporate Fleet Insurance Policy models.

Fleet managers track insurance policies for company vehicles — liability,
collision, comprehensive coverage — with expiry date alerts.

Models:
  CorporateFleetInsurancePolicy
      — one record per insurance policy attached to a fleet vehicle.

Tables:
  corporate_fleet_insurance_policies
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


class InsuranceType(str, PyEnum):
    """Category of fleet vehicle insurance coverage."""

    liability = "liability"
    collision = "collision"
    comprehensive = "comprehensive"
    commercial_auto = "commercial_auto"
    uninsured_motorist = "uninsured_motorist"
    other = "other"


class CorporateFleetInsurancePolicy(Base):
    """An insurance policy record for a corporate fleet vehicle.

    Admins create records linking insurance policies to fleet vehicles,
    tracking policy numbers, coverage types, amounts, and expiry dates.
    Expiry date alerts allow fleet managers to renew policies before lapse.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        policy_number: Insurance policy number, unique per account.
        insurance_type: Category of coverage (InsuranceType enum).
        provider_name: Name of the insurance provider.
        coverage_amount_usd: Maximum coverage amount in USD, nullable.
        deductible_usd: Policy deductible amount in USD, nullable.
        premium_annual_usd: Annual premium cost in USD, nullable.
        policy_start_date: Date the policy becomes effective.
        policy_end_date: Date the policy expires.
        is_active: True when the policy is currently active.
        notes: Free-text notes, nullable.
        created_by_id: FK to users.id (SET NULL), nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_insurance_policies"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "policy_number",
            name="uq_fleet_insurance_account_policy_number",
        ),
        Index("ix_fleet_insurance_account_id", "account_id"),
        Index("ix_fleet_insurance_vehicle_id", "fleet_vehicle_id"),
        Index("ix_fleet_insurance_end_date", "policy_end_date"),
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

    policy_number: Mapped[str] = mapped_column(String(100), nullable=False)

    insurance_type: Mapped[InsuranceType] = mapped_column(
        Enum(InsuranceType, name="insurancetype"),
        nullable=False,
    )

    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)

    coverage_amount_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )

    deductible_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    premium_annual_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    policy_start_date: Mapped[date] = mapped_column(Date, nullable=False)

    policy_end_date: Mapped[date] = mapped_column(Date, nullable=False)

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
