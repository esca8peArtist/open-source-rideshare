import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class VehicleType(str, enum.Enum):
    SEDAN = "sedan"
    SUV = "suv"
    VAN = "van"
    MINIVAN = "minivan"
    TRUCK = "truck"
    HATCHBACK = "hatchback"
    COUPE = "coupe"
    WAGON = "wagon"
    OTHER = "other"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )
    vehicle_type: Mapped[VehicleType] = mapped_column(Enum(VehicleType))
    make: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    year: Mapped[int]
    color: Mapped[str] = mapped_column(String(50))
    license_plate: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[int] = mapped_column(default=4)
    is_wheelchair_accessible: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    driver_profile = relationship(
        "DriverProfile", back_populates="vehicles", foreign_keys=[driver_profile_id]
    )
