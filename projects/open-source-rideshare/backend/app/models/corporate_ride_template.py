"""Corporate Ride Template model.

Corporate admins define named, reusable booking configurations — saved routes
with pre-filled pickup/dropoff addresses, preferred vehicle type, and default
cost centre / trip purpose.  Employees browse templates and get pre-filled
data when booking, reducing friction for frequent corporate trips (airport
runs, hotel transfers, office-to-client-site routes, etc.).

Table:
  corporate_ride_templates — one row per named template per account.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateRideTemplate(Base):
    """A saved booking configuration that employees can use to quickly book rides.

    Admins create templates for common routes (e.g. "Airport Express",
    "HQ to Client HQ", "Shift Pickup").  Each template stores pickup and
    dropoff location details, preferred vehicle type, and accounting defaults.
    A ``use_count`` tracks how often the template is invoked so admins can
    surface the most popular ones.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        created_by_id: FK to users (SET NULL on deletion).
        name: Human-readable template name, unique per account.
        description: Optional longer description of the route/purpose.
        pickup_location_name: Friendly name for the pickup point
            (e.g. "HQ Lobby", "Terminal 2").
        pickup_address_line1: Optional street address line 1.
        pickup_address_line2: Optional street address line 2.
        pickup_city: Optional city.
        pickup_state: Optional state/province.
        pickup_country: Optional country.
        pickup_postal_code: Optional postal/zip code.
        pickup_latitude: Optional latitude for geo lookups.
        pickup_longitude: Optional longitude for geo lookups.
        dropoff_location_name: Friendly name for the dropoff point.
        dropoff_address_line1: Optional street address line 1.
        dropoff_address_line2: Optional street address line 2.
        dropoff_city: Optional city.
        dropoff_state: Optional state/province.
        dropoff_country: Optional country.
        dropoff_postal_code: Optional postal/zip code.
        dropoff_latitude: Optional latitude for geo lookups.
        dropoff_longitude: Optional longitude for geo lookups.
        vehicle_type: Optional preferred vehicle type string
            (e.g. "standard", "premium", "xl", "wav").
        default_cost_center_id: FK to corporate_cost_centers (SET NULL).
        default_trip_purpose_id: FK to corporate_trip_purposes (SET NULL).
        notes: Optional extra notes shown to employees when using the template.
        use_count: How many times this template has been invoked.  Incremented
            by the service layer on each ``record_template_use`` call.
        is_active: When False the template is hidden from member list views.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_ride_templates"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "name", name="uq_corp_ride_template_account_name"
        ),
        Index("ix_corp_ride_template_account_id", "account_id"),
        Index("ix_corp_ride_template_is_active", "is_active"),
        Index("ix_corp_ride_template_use_count", "use_count"),
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

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Pickup ----

    pickup_location_name: Mapped[str] = mapped_column(String(200), nullable=False)

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

    # ---- Dropoff ----

    dropoff_location_name: Mapped[str] = mapped_column(String(200), nullable=False)

    dropoff_address_line1: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    dropoff_address_line2: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    dropoff_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    dropoff_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    dropoff_country: Mapped[str | None] = mapped_column(String(100), nullable=True)

    dropoff_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    dropoff_latitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    dropoff_longitude: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )

    # ---- Booking defaults ----

    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    default_cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    default_trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    default_cost_center = relationship(
        "CorporateCostCenter",
        foreign_keys=[default_cost_center_id],
        lazy="raise",
    )
    default_trip_purpose = relationship(
        "CorporateTripPurpose",
        foreign_keys=[default_trip_purpose_id],
        lazy="raise",
    )
