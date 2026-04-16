"""Corporate Shift models.

Companies with shift workers (healthcare, manufacturing, security) need
coordinated transportation to/from shift start and end times.  Admins define
named shifts with timing and work location; employees are assigned with their
personal pickup addresses.

Tables:
  corporate_shifts            — one row per named shift definition.
  corporate_shift_assignments — junction table linking members to shifts with
                                their personal pickup address and preferences.
"""

from __future__ import annotations

from datetime import datetime, time

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
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateShift(Base):
    """A named recurring shift with a fixed work location and schedule.

    Admins create shifts (e.g. "Morning Shift", "Night Shift") for a corporate
    account.  Employees are then assigned to shifts via CorporateShiftAssignment.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable shift name, unique per account.
        description: Optional longer description.
        work_location_name: Name of the work site (e.g. "Main Plant").
        work_address_line1: Optional street address line 1.
        work_address_line2: Optional street address line 2.
        work_city: Optional city.
        work_state: Optional state/province.
        work_country: Optional country.
        work_postal_code: Optional postal/zip code.
        work_latitude: Optional latitude for geo lookups.
        work_longitude: Optional longitude for geo lookups.
        shift_start_time: Time of day when the shift begins (e.g. 06:00).
        shift_end_time: Time of day when the shift ends (e.g. 14:00).
        days_of_week: JSON list of ints (0=Monday … 6=Sunday) when shift runs.
        is_active: When False the shift is hidden from default views.
        created_by_id: FK to users — who created the shift (SET NULL on deletion).
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shifts"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_corp_shift_account_name"),
        Index("ix_corp_shift_account_id", "account_id"),
        Index("ix_corp_shift_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    work_location_name: Mapped[str] = mapped_column(String(200), nullable=False)

    work_address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)

    work_address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)

    work_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    work_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    work_country: Mapped[str | None] = mapped_column(String(100), nullable=True)

    work_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    work_latitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    work_longitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    shift_start_time: Mapped[time] = mapped_column(Time(), nullable=False)

    shift_end_time: Mapped[time] = mapped_column(Time(), nullable=False)

    # JSON list of ints: 0=Monday, 1=Tuesday, … 6=Sunday
    days_of_week: Mapped[list] = mapped_column(
        sa.JSON(), nullable=False, default=list
    )

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

    # Relationships
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    assignments: Mapped[list["CorporateShiftAssignment"]] = relationship(
        "CorporateShiftAssignment",
        back_populates="shift",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateShiftAssignment(Base):
    """An assignment linking a member to a shift with their pickup details.

    Stores the employee's personal pickup address and scheduling preferences.
    The ``auto_request_rides`` flag is a preference placeholder — it does not
    trigger actual ride creation in this implementation.

    Attributes:
        id: Integer primary key.
        shift_id: FK to corporate_shifts (CASCADE delete).
        member_id: FK to corporate_account_members (CASCADE delete).
        pickup_address_line1: Optional pickup street address line 1.
        pickup_address_line2: Optional pickup street address line 2.
        pickup_city: Optional pickup city.
        pickup_state: Optional pickup state/province.
        pickup_country: Optional pickup country.
        pickup_postal_code: Optional pickup postal/zip code.
        pickup_latitude: Optional pickup latitude for geo lookups.
        pickup_longitude: Optional pickup longitude for geo lookups.
        auto_request_rides: Preference flag — stored but does not trigger rides.
        advance_booking_minutes: How many minutes before shift to book the ride.
        is_active: When False the assignment is inactive.
        assigned_by_id: FK to users — who created the assignment (SET NULL).
        notes: Optional notes about the assignment.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shift_assignments"
    __table_args__ = (
        UniqueConstraint("shift_id", "member_id", name="uq_corp_shift_assignment"),
        Index("ix_corp_shift_assignment_shift_id", "shift_id"),
        Index("ix_corp_shift_assignment_member_id", "member_id"),
        Index("ix_corp_shift_assignment_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    shift_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_shifts.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )

    pickup_address_line1: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    pickup_address_line2: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    pickup_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    pickup_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    pickup_country: Mapped[str | None] = mapped_column(String(100), nullable=True)

    pickup_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    pickup_latitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    pickup_longitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    # Preference flag only — does not trigger ride creation.
    auto_request_rides: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    advance_booking_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    assigned_by_id: Mapped[int | None] = mapped_column(
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

    # Relationships
    shift: Mapped["CorporateShift"] = relationship(
        "CorporateShift", back_populates="assignments", lazy="raise"
    )
    assigned_by = relationship("User", foreign_keys=[assigned_by_id], lazy="raise")
