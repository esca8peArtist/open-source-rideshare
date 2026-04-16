"""Corporate Travel Itinerary models.

Employees create named business trips (e.g. "Q2 Sales Conference NYC") that
group multiple rides for consolidated expense reporting.  All rides under an
itinerary share a cost center and trip purpose, so employees submit one report
instead of many.

Tables:
  corporate_travel_itineraries — one row per named business trip.
  corporate_itinerary_rides    — junction table linking rides to itineraries.
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateTravelItinerary(Base):
    """A named business trip that groups rides for expense reporting.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        created_by_id: FK to users — employee who created the itinerary
            (SET NULL on user deletion).
        title: Human-readable trip name, e.g. "Q2 Sales Conference NYC".
        description: Optional longer description of the trip.
        start_date: Optional planned start date.
        end_date: Optional planned end date.
        cost_center_id: Optional FK to corporate_cost_centers (SET NULL).
            All rides in this itinerary default to this cost center.
        trip_purpose_id: Optional FK to corporate_trip_purposes (SET NULL).
            All rides in this itinerary share this purpose.
        status: Lifecycle state — draft / active / completed / cancelled.
            Stored as a plain string (not a PG enum type) for flexibility.
        is_active: When False the itinerary is hidden from default list views.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_travel_itineraries"
    __table_args__ = (
        Index("ix_corp_itinerary_account_id", "account_id"),
        Index("ix_corp_itinerary_created_by", "created_by_id"),
        Index("ix_corp_itinerary_status", "account_id", "status"),
        Index("ix_corp_itinerary_active", "account_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    start_date: Mapped[sa.Date | None] = mapped_column(sa.Date, nullable=True)

    end_date: Mapped[sa.Date | None] = mapped_column(sa.Date, nullable=True)

    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Stored as String — not a PG enum type — so we can add values without migrations.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )

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

    # Relationships
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    cost_center = relationship(
        "CorporateCostCenter", foreign_keys=[cost_center_id], lazy="raise"
    )
    trip_purpose = relationship(
        "CorporateTripPurpose", foreign_keys=[trip_purpose_id], lazy="raise"
    )


class CorporateItineraryRide(Base):
    """A ride associated with a corporate travel itinerary.

    SET NULL on ride deletion so the association record persists even after the
    ride row is removed — useful for audit and expense-report history.

    Attributes:
        id: Integer primary key.
        itinerary_id: FK to corporate_travel_itineraries (CASCADE delete).
        ride_id: FK to rides (SET NULL on ride deletion), nullable.
        added_by_id: FK to users — who added the ride (SET NULL on deletion).
        notes: Optional note about why this ride belongs to the itinerary.
        added_at: When the ride was added to the itinerary.
    """

    __tablename__ = "corporate_itinerary_rides"
    __table_args__ = (
        UniqueConstraint("itinerary_id", "ride_id", name="uq_itinerary_ride"),
        Index("ix_itinerary_ride_itinerary", "itinerary_id"),
        Index("ix_itinerary_ride_ride", "ride_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    itinerary_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_travel_itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )

    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
    )

    added_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    itinerary = relationship(
        "CorporateTravelItinerary", foreign_keys=[itinerary_id], lazy="raise"
    )
    ride = relationship("Ride", foreign_keys=[ride_id], lazy="raise")
    added_by = relationship("User", foreign_keys=[added_by_id], lazy="raise")
