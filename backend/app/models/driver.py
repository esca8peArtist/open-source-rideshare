import enum
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class MembershipStatus(str, enum.Enum):
    """Cooperative membership standing for a driver.

    Controls whether a driver is eligible to go online and accept rides.
    Only drivers with status ``active`` pass the compliance gate.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"       # Temporary; can be reinstated
    PROBATION = "probation"       # Monitored period; still allowed online
    COMPLIANCE_HOLD = "compliance_hold"  # Auto-set when a doc expires
    TERMINATED = "terminated"     # Permanent; cannot be reinstated online


class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(50))
    vehicle_make: Mapped[str] = mapped_column(String(100))
    vehicle_model: Mapped[str] = mapped_column(String(100))
    vehicle_year: Mapped[int]
    vehicle_color: Mapped[str] = mapped_column(String(50))
    license_plate: Mapped[str] = mapped_column(String(20))
    license_number: Mapped[str] = mapped_column(String(50))
    insurance_policy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    background_check_status: Mapped[str] = mapped_column(String(20), default="pending")
    rating_avg: Mapped[float] = mapped_column(default=5.0)
    total_trips: Mapped[int] = mapped_column(default=0)
    is_online: Mapped[bool] = mapped_column(default=False)
    is_approved: Mapped[bool] = mapped_column(default=False)
    active_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", use_alter=True), nullable=True
    )
    current_location: Mapped[bytes | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=True
    )

    # ── Compliance fields (Sprint 1) ────────────────────────────────────────
    # These enable the compliance gate that prevents drivers with expired
    # documents from going online.  All expiry fields are nullable so that
    # existing driver records remain valid until the cooperative populates them.

    membership_status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, name="membershipstatus"),
        default=MembershipStatus.ACTIVE,
        index=True,
    )
    license_expiry: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    background_check_expiry: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    vehicle_inspection_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_endorsement_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_endorsement_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Jurisdiction the driver is registered under.  Nullable for drivers
    # onboarded before jurisdictions were introduced.
    jurisdiction_id: Mapped[str | None] = mapped_column(
        ForeignKey("jurisdictions.id"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", backref="driver_profile")
    vehicles = relationship(
        "Vehicle", back_populates="driver_profile", foreign_keys="Vehicle.driver_profile_id"
    )
    active_vehicle = relationship(
        "Vehicle", foreign_keys=[active_vehicle_id], post_update=True
    )
    jurisdiction = relationship("Jurisdiction", backref="drivers")
