"""LostItemReport model — tracks lost and found items for rides.

A rider can report a lost item (something left in a car) and a driver can
report a found item (something a passenger left behind). Admins then match
and resolve reports through a defined status workflow.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class LostItemStatus(str, enum.Enum):
    REPORTED = "reported"    # Initial state — item reported missing or found
    MATCHED = "matched"      # Admin linked a found report to a lost report
    CLAIMED = "claimed"      # Rider confirmed and scheduled pickup
    RETURNED = "returned"    # Item physically returned to owner
    DONATED = "donated"      # Unclaimed after 30 days, suitable for donation
    DISCARDED = "discarded"  # Unclaimed after 30 days, not suitable for donation


class LostItemCategory(str, enum.Enum):
    ELECTRONICS = "electronics"
    CLOTHING = "clothing"
    DOCUMENTS = "documents"
    KEYS = "keys"
    BAG = "bag"
    JEWELRY = "jewelry"
    OTHER = "other"


class LostItemReport(Base):
    """A report of a lost or found item associated with a ride.

    Either a rider (reporting something they left behind) or a driver
    (reporting something a passenger left) can create a report. Admins
    match and resolve reports.

    reporter_type distinguishes the direction: "rider" means the rider lost
    something; "driver" means the driver found something.

    matched_report_id is a self-referential FK that links a lost report to its
    corresponding found report once an admin matches them.
    """

    __tablename__ = "lost_item_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Ride association — nullable because reporter may not remember which ride
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id"), nullable=True, index=True
    )

    # Who reported
    reporter_type: Mapped[str] = mapped_column(String(10))  # "rider" | "driver"
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Item details
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[LostItemCategory] = mapped_column(Enum(LostItemCategory))
    color: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Workflow state
    status: Mapped[LostItemStatus] = mapped_column(
        Enum(LostItemStatus), default=LostItemStatus.REPORTED, index=True
    )

    # Resolution fields (populated by admin)
    matched_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("lost_item_reports.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Contact preference
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    ride = relationship("Ride", foreign_keys=[ride_id])
    reporter = relationship("User", foreign_keys=[reporter_id])
    admin = relationship("User", foreign_keys=[admin_id])
    matched_report = relationship(
        "LostItemReport",
        foreign_keys=[matched_report_id],
        remote_side="LostItemReport.id",
        uselist=False,
    )
