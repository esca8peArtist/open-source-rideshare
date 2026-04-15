"""Models for the lost and found system (dual-report design).

Two separate tables represent the two sides of a lost-and-found workflow:

  LafLostItemReport  — a rider reports something they left in a vehicle.
  LafFoundItemReport — a driver reports something a passenger left behind.

An admin matches the two reports, and then records the item as returned,
discarded, or — for lost reports — closed with no match.

The "Laf" prefix (Lost And Found) distinguishes these model classes from the
earlier LostItemReport in app.models.lost_found, which uses a single unified
table with a reporter_type field.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ItemCategory(str, enum.Enum):
    """Category of a lost or found item."""

    ELECTRONICS = "electronics"
    CLOTHING = "clothing"
    DOCUMENTS = "documents"
    BAGS = "bags"
    JEWELRY = "jewelry"
    KEYS = "keys"
    OTHER = "other"


class ContactPreference(str, enum.Enum):
    """How a rider prefers to be contacted about their lost item."""

    APP_MESSAGE = "app_message"
    PHONE = "phone"
    EMAIL = "email"


class LafLostItemStatus(str, enum.Enum):
    """Lifecycle states for a rider's lost item report."""

    OPEN = "open"
    MATCHED = "matched"
    RETURNED = "returned"
    CLOSED_NO_MATCH = "closed_no_match"


class LafFoundItemStatus(str, enum.Enum):
    """Lifecycle states for a driver's found item report."""

    PENDING_MATCH = "pending_match"
    MATCHED = "matched"
    RETURNED_TO_OWNER = "returned_to_owner"
    DISCARDED = "discarded"


class LafLostItemReport(Base):
    """A rider's report of an item left in a rideshare vehicle.

    ride_id is optional — the rider may not remember which specific ride.
    matched_found_report_id is set by an admin when a corresponding
    LafFoundItemReport is identified.
    """

    __tablename__ = "laf_lost_item_reports"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Who lost it
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    # Optional ride association
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id"), nullable=True, index=True
    )

    # Item description
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[ItemCategory] = mapped_column(Enum(ItemCategory), index=True)
    date_lost: Mapped[date] = mapped_column(Date, nullable=False)

    # How to reach the rider
    contact_preference: Mapped[ContactPreference] = mapped_column(
        Enum(ContactPreference), nullable=False
    )

    # Workflow
    status: Mapped[LafLostItemStatus] = mapped_column(
        Enum(LafLostItemStatus), default=LafLostItemStatus.OPEN, index=True
    )

    # Populated by admin on match
    matched_found_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("laf_found_item_reports.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    rider = relationship("User", foreign_keys=[rider_id])
    ride = relationship("Ride", foreign_keys=[ride_id])
    matched_found_report = relationship(
        "LafFoundItemReport",
        foreign_keys=[matched_found_report_id],
        back_populates="matched_lost_report_ref",
    )


class LafFoundItemReport(Base):
    """A driver's report of an item left by a passenger.

    ride_id is optional — the driver may not know which ride the item
    came from (e.g. found it at the end of a shift).
    matched_lost_report_id is set by an admin when a corresponding
    LafLostItemReport is identified.
    """

    __tablename__ = "laf_found_item_reports"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Who found it
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    # Optional ride association
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id"), nullable=True, index=True
    )

    # Item description
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[ItemCategory] = mapped_column(Enum(ItemCategory), index=True)
    date_found: Mapped[date] = mapped_column(Date, nullable=False)

    # Where is the driver keeping it
    storage_location: Mapped[str] = mapped_column(String(255), nullable=False)

    # Workflow
    status: Mapped[LafFoundItemStatus] = mapped_column(
        Enum(LafFoundItemStatus), default=LafFoundItemStatus.PENDING_MATCH, index=True
    )

    # Populated by admin on match
    matched_lost_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("laf_lost_item_reports.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    driver = relationship("User", foreign_keys=[driver_id])
    ride = relationship("Ride", foreign_keys=[ride_id])
    matched_lost_report_ref = relationship(
        "LafLostItemReport",
        foreign_keys="LafLostItemReport.matched_found_report_id",
        back_populates="matched_found_report",
        uselist=False,
    )
