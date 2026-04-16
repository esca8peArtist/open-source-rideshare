"""Corporate Employee Transport Preference model.

Each employee in a corporate account can maintain a personal transport
preference profile.  The preferences are stored as a single row per
(account, member) pair and are used to pre-populate booking defaults
when an employee creates a corporate ride.

Fields:
  - preferred_vehicle_type   — sedan / suv / luxury / wav (free string; nullable)
  - accessibility_needs      — JSONB list of need tags, e.g.
                               ["wheelchair_accessible", "service_animal"]
  - home_address / lat / lng — home pick-up location for shift/commuter rides
  - default_cost_center_id   — pre-fills the cost centre on new bookings
  - default_trip_purpose_id  — pre-fills the trip purpose on new bookings
  - preferred_pickup_note    — free-text driver instructions
  - notify_sms_number        — phone number for SMS ride-status updates
  - is_active                — soft-disable (retains data, ignored by booking)

Table:
  corporate_employee_transport_preferences — one row per (account, member).
"""

from __future__ import annotations

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateEmployeeTransportPreference(Base):
    """Personal transport preference profile for a corporate account employee.

    Created on first access (upsert-on-read semantics) and updated by the
    employee themselves or by an account admin.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to users (CASCADE delete) — the employee who owns this
            preference row.
        preferred_vehicle_type: Nullable free-form vehicle category string
            (e.g. ``sedan``, ``suv``, ``luxury``, ``wav``).
        accessibility_needs: Optional JSONB list of accessibility requirement
            tags.  Recognised values include ``wheelchair_accessible``,
            ``service_animal``, ``extra_boarding_time``,
            ``front_seat_required``, and ``audio_assistance``.
        home_address: Optional full street address for the employee's home —
            used to pre-fill pickup on commuter / shift rides.
        home_latitude: Latitude of the home address.
        home_longitude: Longitude of the home address.
        default_cost_center_id: FK to corporate_cost_centers (SET NULL).
            When set, new corporate bookings by this employee pre-select this
            cost centre.
        default_trip_purpose_id: FK to corporate_trip_purposes (SET NULL).
            When set, new corporate bookings pre-select this trip purpose.
        preferred_pickup_note: Optional free-text driver instructions shown
            on every corporate booking by this employee.
        notify_sms_number: Optional phone number for SMS ride-status updates
            (overrides account-level notification settings for this employee).
        is_active: When False the preference row is retained but ignored by
            the booking flow.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_employee_transport_preferences"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "member_id",
            name="uq_corp_transport_pref_account_member",
        ),
        Index("ix_corp_transport_pref_account_id", "account_id"),
        Index("ix_corp_transport_pref_member_id", "member_id"),
        Index("ix_corp_transport_pref_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    preferred_vehicle_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    # JSONB list of accessibility-need tag strings.
    accessibility_needs: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    home_address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    home_latitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    home_longitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    default_cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    default_trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    preferred_pickup_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    notify_sms_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
