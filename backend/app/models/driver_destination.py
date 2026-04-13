"""Driver destination filter model.

Drivers can activate a destination filter (sometimes called "going-home mode")
so they only receive ride offers whose dropoff location is within a configurable
radius of their chosen destination. When the filter is inactive, the driver
receives all nearby ride offers as normal.

Only one filter row exists per driver (upsert behaviour in the service layer).
The row is never hard-deleted — clearing the filter sets ``is_active=False``.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class DriverDestinationFilter(Base):
    """One-row-per-driver destination filter record.

    Columns
    -------
    driver_id          FK to driver_profiles.id (unique — one filter per driver)
    destination_lat    Latitude of the driver's target destination
    destination_lon    Longitude of the driver's target destination
    radius_km          How close a ride's dropoff must be to the destination
                       (1.0–50.0 km; default 5.0)
    is_active          True means the filter is in effect; False means disabled
    expires_at         Optional wall-clock time after which the filter is
                       automatically treated as inactive by the matching engine
    created_at / updated_at
    """

    __tablename__ = "driver_destination_filters"

    __table_args__ = (
        UniqueConstraint("driver_id", name="uq_driver_destination_filters_driver_id"),
        Index("idx_driver_destination_filters_driver_id", "driver_id"),
        Index("idx_driver_destination_filters_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"),
        nullable=False,
        unique=True,
    )

    destination_lat: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Acceptable dropoff radius in km (1–50)
    radius_km: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Optional auto-expiry (None = no expiry)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
