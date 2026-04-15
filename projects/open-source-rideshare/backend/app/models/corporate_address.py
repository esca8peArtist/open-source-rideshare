"""Corporate Address Book model.

Enterprise accounts maintain a shared library of named locations — offices,
client sites, airports, hotels — that employees browse and select when booking
rides.  Each address can auto-tag rides with a default cost center and trip
purpose, reducing manual entry for common corporate destinations.

CorporateAddress — one row per named location per account.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateAddress(Base):
    """A named, reusable location in a corporate account's address book.

    Attributes:
        id: Auto-incrementing primary key.
        account_id: The corporate account this address belongs to.
        name: Human-readable display label (e.g. "HQ Office", "ORD Airport").
        address_line_1: Street address.
        address_line_2: Suite/floor/unit (optional).
        city: City.
        state: State or province code.
        zip_code: Postal code (optional).
        country: ISO 3166-1 alpha-2 country code (default "US").
        latitude: Geocoded latitude for map display and matching (optional).
        longitude: Geocoded longitude (optional).
        notes: Special instructions for drivers/riders (e.g. "Loading dock B").
        is_pickup_point: Address may be used as a ride pickup location.
        is_dropoff_point: Address may be used as a ride dropoff location.
        default_cost_center_id: Cost center to auto-assign when this address is
            used for pickup or dropoff.
        default_trip_purpose_id: Trip purpose to auto-assign when used.
        is_active: Soft-delete flag; inactive addresses are hidden from employees.
        created_by_id: Admin who added this address.
        created_at / updated_at: Audit timestamps.
    """

    __tablename__ = "corporate_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Street address components
    address_line_1: Mapped[str] = mapped_column(String(500), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, server_default="US")

    # Geocoded coordinates for map display and proximity matching
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    # Driver/rider instructions
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Whether this location can serve as pickup and/or dropoff
    is_pickup_point: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_dropoff_point: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Optional auto-tagging defaults applied to rides using this address
    default_cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
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

    # Relationships
    account = relationship(
        "BusinessAccount",
        foreign_keys=[account_id],
        backref="addresses",
    )
    default_cost_center = relationship(
        "CorporateCostCenter",
        foreign_keys=[default_cost_center_id],
    )
    default_trip_purpose = relationship(
        "CorporateTripPurpose",
        foreign_keys=[default_trip_purpose_id],
    )
    created_by = relationship(
        "User",
        foreign_keys=[created_by_id],
    )
