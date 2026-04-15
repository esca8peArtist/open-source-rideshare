"""Trusted contact and trip sharing models.

Riders can register up to 5 trusted contacts (family, friends, etc.).
When a ride starts, the platform can notify those contacts with trip details
and send a follow-up when the ride completes.

TrustedContact  — a rider's registered contact person
TripShareRecord — log of which contacts were notified for a given ride
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

MAX_TRUSTED_CONTACTS = 5


class TrustedContact(Base):
    __tablename__ = "trusted_contacts"
    __table_args__ = (
        UniqueConstraint("user_id", "phone", name="uq_trusted_contact_user_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    relationship_label: Mapped[str] = mapped_column(String(80), default="")  # e.g. "Mom", "Partner"

    # If True, this contact is notified automatically every time the rider starts a ride
    share_automatically: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", foreign_keys=[user_id])
    trip_shares = relationship("TripShareRecord", back_populates="contact")


class TripShareRecord(Base):
    """Records that a contact was notified about a specific ride."""

    __tablename__ = "trip_share_records"
    __table_args__ = (
        UniqueConstraint("ride_id", "contact_id", name="uq_trip_share_ride_contact"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("trusted_contacts.id"), index=True)

    # Timestamps for each notification type sent
    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    start_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    complete_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contact = relationship("TrustedContact", back_populates="trip_shares")
    ride = relationship("Ride")
