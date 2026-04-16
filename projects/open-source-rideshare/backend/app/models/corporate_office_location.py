"""Corporate Office Location & Membership models.

Enterprise corporate accounts may define named office locations.  Employees
(account members) can be assigned to one or more offices; exactly one office
per member may be marked as their *primary* office.  Admins can designate at
most one office per account as headquarters.

Models:
  CorporateOfficeLocation
      — named physical address for a corporate account
  CorporateOfficeMembership
      — many-to-many link between office locations and account members

Table names:
  corporate_office_locations
  corporate_office_memberships
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateOfficeLocation(Base):
    """A named physical office location belonging to a corporate account.

    At most one location per account may have ``is_headquarters=True`` at any
    time.  The service layer is responsible for clearing the previous HQ flag
    when a new one is set.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable office name, unique per account.
        description: Optional longer description.
        address_line1: Street address.
        address_line2: Suite / floor / additional address info (optional).
        city: City name.
        state: State or province.
        postal_code: Postal / ZIP code.
        country: ISO country code or full name (default "US").
        latitude: Optional GPS latitude for map display.
        longitude: Optional GPS longitude for map display.
        default_cost_center_id: FK to CorporateCostCenter (SET NULL) — the
            cost centre pre-filled on bookings for employees at this office.
        is_headquarters: True for the single HQ office of the account.
        is_active: Soft-delete flag; inactive offices are hidden from members.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_office_locations"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "name",
            name="uq_corp_office_location_account_name",
        ),
        Index("ix_corp_office_loc_account_id", "account_id"),
        Index("ix_corp_office_loc_account_active", "account_id", "is_active"),
        Index(
            "ix_corp_office_loc_account_hq",
            "account_id",
            "is_headquarters",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)

    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)

    city: Mapped[str] = mapped_column(String(100), nullable=False)

    state: Mapped[str] = mapped_column(String(100), nullable=False)

    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)

    country: Mapped[str] = mapped_column(
        String(100), nullable=False, default="US"
    )

    latitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    longitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    default_cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_headquarters: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

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
    default_cost_center = relationship(
        "CorporateCostCenter",
        foreign_keys=[default_cost_center_id],
        lazy="raise",
    )
    memberships = relationship(
        "CorporateOfficeMembership",
        back_populates="office",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateOfficeMembership(Base):
    """Assignment of a corporate account member to an office location.

    A member may belong to multiple offices, but at most one membership per
    member per account may have ``is_primary=True``.  The service layer
    enforces this constraint: assigning a new primary office clears the
    existing primary membership for that member within the account.

    ``account_id`` is denormalised here for efficient platform-admin queries
    that need to join on the account without fetching the office row.

    Attributes:
        id: UUID primary key.
        office_id: FK to CorporateOfficeLocation (CASCADE delete).
        member_id: FK to BusinessAccountMember (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        is_primary: True if this is the member's primary office.
        assigned_by_id: FK to users (SET NULL) — admin who created the record.
        notes: Optional free-text notes about the assignment.
        is_active: Soft flag for inactive assignments.
        created_at: UTC creation timestamp.
    """

    __tablename__ = "corporate_office_memberships"
    __table_args__ = (
        UniqueConstraint(
            "office_id",
            "member_id",
            name="uq_corp_office_membership_office_member",
        ),
        Index("ix_corp_office_mem_office_id", "office_id"),
        Index("ix_corp_office_mem_member_id", "member_id"),
        Index("ix_corp_office_mem_account_id", "account_id"),
        Index("ix_corp_office_mem_member_primary", "member_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    office_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_office_locations.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    office = relationship(
        "CorporateOfficeLocation",
        foreign_keys=[office_id],
        back_populates="memberships",
        lazy="raise",
    )
    member = relationship(
        "BusinessAccountMember",
        foreign_keys=[member_id],
        lazy="raise",
    )
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    assigned_by = relationship(
        "User", foreign_keys=[assigned_by_id], lazy="raise"
    )
