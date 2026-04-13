import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class WaypointStatus(str, enum.Enum):
    PENDING = "pending"
    ARRIVED = "arrived"
    DEPARTED = "departed"
    SKIPPED = "skipped"


class RideWaypoint(Base):
    __tablename__ = "ride_waypoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)  # 1-based position in route

    address: Mapped[str] = mapped_column(String(500))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)

    status: Mapped[WaypointStatus] = mapped_column(
        Enum(WaypointStatus), default=WaypointStatus.PENDING
    )
    wait_time_minutes: Mapped[int] = mapped_column(Integer, default=3)  # max 10
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    estimated_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    departed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ride = relationship("Ride", backref="waypoints")
