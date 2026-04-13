import enum
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.vehicle import VehicleServiceCategory


class RideStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    REQUESTED = "requested"
    MATCHED = "matched"
    DRIVER_EN_ROUTE = "driver_en_route"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Ride(Base):
    __tablename__ = "rides"

    id: Mapped[int] = mapped_column(primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[RideStatus] = mapped_column(Enum(RideStatus), default=RideStatus.REQUESTED)

    pickup_location: Mapped[bytes] = mapped_column(Geometry(geometry_type="POINT", srid=4326))
    dropoff_location: Mapped[bytes] = mapped_column(Geometry(geometry_type="POINT", srid=4326))
    pickup_address: Mapped[str] = mapped_column(String(500))
    dropoff_address: Mapped[str] = mapped_column(String(500))

    estimated_fare: Mapped[float]
    actual_fare: Mapped[float | None] = mapped_column(nullable=True)
    distance_km: Mapped[float | None] = mapped_column(nullable=True)
    duration_min: Mapped[float | None] = mapped_column(nullable=True)
    tip_amount: Mapped[float] = mapped_column(default=0.0)
    promo_code_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    promo_discount: Mapped[float] = mapped_column(default=0.0)

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_pool: Mapped[bool] = mapped_column(default=False)
    pool_id: Mapped[int | None] = mapped_column(ForeignKey("ride_pools.id"), nullable=True, index=True)
    accessibility_required: Mapped[bool] = mapped_column(default=False)
    vehicle_type_preference: Mapped[VehicleServiceCategory | None] = mapped_column(
        Enum(VehicleServiceCategory), nullable=True
    )

    dispatch_retry_count: Mapped[int] = mapped_column(default=0)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reminder tracking — prevents duplicate reminders for scheduled rides
    reminder_1hr_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_15min_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # If generated from a recurring ride template
    recurring_ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_rides.id"), nullable=True, index=True
    )

    rider_rating: Mapped[int | None] = mapped_column(nullable=True)
    driver_rating: Mapped[int | None] = mapped_column(nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rider = relationship("User", foreign_keys=[rider_id], backref="rides_as_rider")
    driver = relationship("User", foreign_keys=[driver_id], backref="rides_as_driver")
