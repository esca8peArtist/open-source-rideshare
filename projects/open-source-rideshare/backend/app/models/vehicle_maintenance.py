import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class MaintenanceType(str, enum.Enum):
    OIL_CHANGE = "oil_change"
    TIRE_ROTATION = "tire_rotation"
    TIRE_REPLACEMENT = "tire_replacement"
    BRAKE_INSPECTION = "brake_inspection"
    BRAKE_REPLACEMENT = "brake_replacement"
    AIR_FILTER = "air_filter"
    CABIN_FILTER = "cabin_filter"
    BATTERY_REPLACEMENT = "battery_replacement"
    COOLANT_FLUSH = "coolant_flush"
    TRANSMISSION_SERVICE = "transmission_service"
    SPARK_PLUGS = "spark_plugs"
    BELT_REPLACEMENT = "belt_replacement"
    WIPER_BLADES = "wiper_blades"
    ANNUAL_INSPECTION = "annual_inspection"
    OTHER = "other"


class VehicleMaintenanceLog(Base):
    __tablename__ = "vehicle_maintenance_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )

    maintenance_type: Mapped[MaintenanceType] = mapped_column(Enum(MaintenanceType))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Service details
    date_serviced: Mapped[date] = mapped_column(Date)
    mileage_at_service: Mapped[int | None] = mapped_column(nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)

    # Next service schedule (either date or mileage — at least one expected)
    next_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_service_mileage: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    vehicle = relationship("Vehicle", backref="maintenance_logs")
    driver_profile = relationship("DriverProfile", backref="maintenance_logs")
