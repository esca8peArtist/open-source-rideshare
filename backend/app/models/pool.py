import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PoolStatus(str, enum.Enum):
    FORMING = "forming"          # Accepting riders, not yet dispatched
    MATCHED = "matched"          # Driver assigned, heading to first pickup
    IN_PROGRESS = "in_progress"  # At least one rider picked up
    COMPLETED = "completed"      # All riders dropped off
    CANCELLED = "cancelled"      # Pool dissolved (no riders left)


class LegStatus(str, enum.Enum):
    WAITING_PICKUP = "waiting_pickup"
    PICKED_UP = "picked_up"
    DROPPED_OFF = "dropped_off"
    CANCELLED = "cancelled"


class RidePool(Base):
    __tablename__ = "ride_pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[PoolStatus] = mapped_column(Enum(PoolStatus), default=PoolStatus.FORMING)
    max_riders: Mapped[int] = mapped_column(default=3)

    # Combined route stats (updated as riders are added/removed)
    total_distance_km: Mapped[float | None] = mapped_column(nullable=True)
    total_duration_min: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    driver = relationship("User", foreign_keys=[driver_id])
    legs = relationship("PoolLeg", back_populates="pool", order_by="PoolLeg.pickup_order")


class PoolLeg(Base):
    __tablename__ = "pool_legs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("ride_pools.id"), index=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), unique=True, index=True)

    pickup_order: Mapped[int]     # 1, 2, 3 — sequence of pickups
    dropoff_order: Mapped[int]    # 1, 2, 3 — sequence of dropoffs

    # How much extra distance this rider's detour adds vs their direct route
    detour_distance_km: Mapped[float] = mapped_column(default=0.0)
    fare_discount_percent: Mapped[float] = mapped_column(default=25.0)

    status: Mapped[LegStatus] = mapped_column(Enum(LegStatus), default=LegStatus.WAITING_PICKUP)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dropped_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pool = relationship("RidePool", back_populates="legs")
    ride = relationship("Ride", backref="pool_leg")
