"""Corporate Parking Management models.

Enterprise accounts manage their physical parking facilities for employees.
Admins define named facilities, populate individual spots within each facility,
and assign spots to employees.  Assignments are lifecycle-managed (start/end
dates) so historical records are preserved.

Models:
  CorporateParkingFacility
      — a named parking facility (garage, lot, structure) belonging to an account
  CorporateParkingSpot
      — an individual parking spot within a facility
  CorporateParkingAssignment
      — an active or historical assignment of a spot to a corporate member

Tables:
  corporate_parking_facilities
  corporate_parking_spots
  corporate_parking_assignments
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class FacilityType(str, enum.Enum):
    surface_lot = "surface_lot"
    parking_garage = "parking_garage"
    covered_structure = "covered_structure"
    underground = "underground"


class SpotType(str, enum.Enum):
    standard = "standard"
    accessible = "accessible"
    ev_charging = "ev_charging"
    motorcycle = "motorcycle"
    oversized = "oversized"
    reserved = "reserved"
    visitor = "visitor"


class CorporateParkingFacility(Base):
    """A named parking facility owned by a corporate account.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable facility name (unique per account).
        description: Optional description.
        address_line1: Street address.
        address_line2: Suite / floor / unit (nullable).
        city: City.
        state: State / province.
        zip_code: Postal code.
        lat: Latitude (nullable).
        lng: Longitude (nullable).
        facility_type: Enum — surface_lot / parking_garage / covered_structure / underground.
        notes: Free-text notes (nullable).
        is_active: Soft-delete flag.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_parking_facilities"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_parking_facility_account_name"),
        Index("ix_parking_facility_account_id", "account_id"),
        Index("ix_parking_facility_is_active", "is_active"),
        Index("ix_parking_facility_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    lat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lng: Mapped[str | None] = mapped_column(String(20), nullable=True)

    facility_type: Mapped[FacilityType] = mapped_column(
        Enum(FacilityType, name="facilitytype"),
        nullable=False,
        default=FacilityType.surface_lot,
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

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    spots = relationship(
        "CorporateParkingSpot",
        back_populates="facility",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateParkingSpot(Base):
    """An individual parking spot within a facility.

    Attributes:
        id: UUID primary key.
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        facility_id: FK to corporate_parking_facilities (CASCADE delete).
        spot_identifier: Human-readable identifier (e.g., "A-12", "L2-B4") — unique per facility.
        spot_type: Enum — standard / accessible / ev_charging / motorcycle / oversized / reserved / visitor.
        floor_level: Optional floor or level label (e.g., "1", "B2").
        is_assigned: True when an active assignment exists for this spot.
        notes: Free-text notes (nullable).
        is_active: Soft-delete flag.
        created_at: UTC creation timestamp.
    """

    __tablename__ = "corporate_parking_spots"
    __table_args__ = (
        UniqueConstraint(
            "facility_id", "spot_identifier", name="uq_parking_spot_facility_identifier"
        ),
        Index("ix_parking_spot_account_id", "account_id"),
        Index("ix_parking_spot_facility_id", "facility_id"),
        Index("ix_parking_spot_is_assigned", "is_assigned"),
        Index("ix_parking_spot_spot_type", "spot_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_parking_facilities.id", ondelete="CASCADE"),
        nullable=False,
    )

    spot_identifier: Mapped[str] = mapped_column(String(50), nullable=False)

    spot_type: Mapped[SpotType] = mapped_column(
        Enum(SpotType, name="spottype"),
        nullable=False,
        default=SpotType.standard,
    )

    floor_level: Mapped[str | None] = mapped_column(String(20), nullable=True)

    is_assigned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    facility = relationship(
        "CorporateParkingFacility",
        foreign_keys=[facility_id],
        back_populates="spots",
        lazy="raise",
    )
    assignments = relationship(
        "CorporateParkingAssignment",
        back_populates="spot",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateParkingAssignment(Base):
    """Assignment of a parking spot to a corporate member.

    Only one active assignment may exist per spot at a time (enforced at the
    service layer).  Historical records are retained by setting is_active=False
    when the assignment ends, so the full assignment history is preserved.

    Attributes:
        id: UUID primary key.
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        spot_id: FK to corporate_parking_spots (CASCADE delete).
        member_id: FK to users (SET NULL) — employee who holds the spot.
        assigned_by_id: FK to users (SET NULL) — admin who created the assignment.
        permit_number: Optional external permit reference (e.g., issued by building management).
        start_date: Date the assignment becomes effective.
        end_date: Date the assignment expires (None = permanent / open-ended).
        is_active: False when the assignment has been ended.
        notes: Free-text notes (nullable).
        ended_at: Timezone-aware timestamp when the assignment was ended.
        ended_by_id: FK to users (SET NULL) — admin who ended the assignment.
        created_at: UTC creation timestamp.
    """

    __tablename__ = "corporate_parking_assignments"
    __table_args__ = (
        Index("ix_parking_assignment_account_id", "account_id"),
        Index("ix_parking_assignment_spot_id", "spot_id"),
        Index("ix_parking_assignment_member_id", "member_id"),
        Index("ix_parking_assignment_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_parking_spots.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    permit_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ended_by_id: Mapped[int | None] = mapped_column(
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
    spot = relationship(
        "CorporateParkingSpot",
        foreign_keys=[spot_id],
        back_populates="assignments",
        lazy="raise",
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    assigned_by = relationship("User", foreign_keys=[assigned_by_id], lazy="raise")
    ended_by = relationship("User", foreign_keys=[ended_by_id], lazy="raise")
