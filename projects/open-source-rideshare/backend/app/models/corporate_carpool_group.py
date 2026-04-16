"""Corporate Carpool Group models.

Corporate employees who share rides together for daily commutes form carpool
groups.  Each group has optional origin/destination coordinates, a departure
time, and an ordered list of member pickup points.

This is distinct from:
  - recurring_rides: personal per-employee schedules
  - batch_booking: admin-created ride batches
  - shifts: work schedules with locations

Models:
  CorporateCarpoolGroup   — a named carpool group within a corporate account
  CorporateCarpoolMember  — an employee enrolled in a carpool group with their
                            personal pickup point and sequence order

Table names:
  corporate_carpool_groups
  corporate_carpool_members
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateCarpoolGroup(Base):
    """A named carpool group belonging to a corporate account.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        name: Human-readable name, unique per account (enforced at service layer).
        description: Optional longer description.
        max_members: Maximum number of members; null means no limit.
        home_base_address: Optional common origin address string.
        home_base_lat / home_base_lng: Coordinates of the common origin.
        destination_address: Optional common destination address string.
        destination_lat / destination_lng: Coordinates of the common destination.
        departure_time: "HH:MM" string representing when the carpool departs.
        days_of_week: JSONB list of ints 0–6 (Mon–Sun) when carpool operates.
        vehicle_type: Optional preferred vehicle type string.
        cost_center_id: FK to corporate_cost_centers.id (SET NULL) — billing center.
        trip_purpose_id: FK to corporate_trip_purposes.id (SET NULL) — purpose tag.
        is_active: Soft-disable flag.
        created_by_id: FK to users.id (SET NULL) — admin who created this group.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_carpool_groups"
    __table_args__ = (
        Index("ix_corp_carpool_group_account_id", "account_id"),
        Index("ix_corp_carpool_group_created_by", "created_by_id"),
        Index("ix_corp_carpool_group_account_active", "account_id", "is_active"),
        Index("ix_corp_carpool_group_account_name", "account_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    max_members: Mapped[int | None] = mapped_column(Integer, nullable=True)

    home_base_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    home_base_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    home_base_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    destination_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    destination_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    destination_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    departure_time: Mapped[str | None] = mapped_column(String(5), nullable=True)

    days_of_week: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    cost_center_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    trip_purpose_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        sa.Integer,
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

    account = relationship("BusinessAccount", foreign_keys=[account_id], lazy="raise")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    cost_center = relationship(
        "CorporateCostCenter", foreign_keys=[cost_center_id], lazy="raise"
    )
    trip_purpose = relationship(
        "CorporateTripPurpose", foreign_keys=[trip_purpose_id], lazy="raise"
    )
    members = relationship(
        "CorporateCarpoolMember",
        back_populates="carpool_group",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class CorporateCarpoolMember(Base):
    """An employee enrolled in a corporate carpool group.

    Attributes:
        id: Integer primary key.
        carpool_group_id: FK to corporate_carpool_groups.id (CASCADE delete).
        account_id: Denormalized FK to corporate_accounts_v2.id (CASCADE delete).
        member_id: FK to users.id (CASCADE delete) — the enrolled employee.
        pickup_address: Optional personal pickup address for this member.
        pickup_lat / pickup_lng: Coordinates of the personal pickup point.
        pickup_sequence: Order of pickups; lower values are picked up earlier.
        is_active: Soft-disable flag for this membership.
        added_by_id: FK to users.id (SET NULL) — admin who added this member.
        notes: Optional free-text notes about this membership.
        joined_at: UTC timestamp when the member was added.
    """

    __tablename__ = "corporate_carpool_members"
    __table_args__ = (
        UniqueConstraint(
            "carpool_group_id",
            "member_id",
            name="uq_carpool_group_member",
        ),
        Index("ix_corp_carpool_member_group_id", "carpool_group_id"),
        Index("ix_corp_carpool_member_account_id", "account_id"),
        Index("ix_corp_carpool_member_member_id", "member_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    carpool_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_carpool_groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    pickup_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pickup_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    pickup_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    pickup_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    added_by_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    carpool_group = relationship(
        "CorporateCarpoolGroup",
        back_populates="members",
        lazy="raise",
    )
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    added_by = relationship("User", foreign_keys=[added_by_id], lazy="raise")
