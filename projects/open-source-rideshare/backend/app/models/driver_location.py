"""Driver real-time location model.

Each driver has a single row that is upserted on every GPS update.
This gives riders and admins the *current* position of a driver
during an active ride or while the driver is available for matching.

Cooperative transparency note: location data is scoped — only the
rider of an active ride (or an admin) can query a driver's position.
We do not expose driver locations to uninvolved parties.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DriverLocation(Base):
    """Last-known GPS position for a driver.

    One row per driver — upserted on each ``POST /drivers/me/location``
    call.  ``updated_at`` is the freshness indicator.

    Fields
    ------
    driver_id       FK → users.id (CASCADE on delete)
    ride_id         FK → rides.id (SET NULL on delete) — current ride,
                    if the driver is on a trip.  NULL when available.
    latitude        Decimal degrees, WGS-84.
    longitude       Decimal degrees, WGS-84.
    accuracy_meters Optional GPS accuracy radius in metres.
    heading         Optional compass bearing (0–360°, clockwise from north).
    speed_kmh       Optional ground speed in km/h.
    is_active       True when the driver is on shift (clocked in).
                    Set to False when the driver clocks out.
    updated_at      Timestamp of the most recent location push.
    """

    __tablename__ = "driver_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    driver_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one row per driver
        index=True,
    )

    ride_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    latitude: Mapped[float] = mapped_column(Float(precision=8), nullable=False)
    longitude: Mapped[float] = mapped_column(Float(precision=8), nullable=False)

    accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)

    # True while the driver is active on shift
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships (not eagerly loaded)
    driver = relationship("User", foreign_keys=[driver_id])
    ride = relationship("Ride", foreign_keys=[ride_id])

    __table_args__ = (
        Index("ix_driver_locations_updated_at", "updated_at"),
        Index("ix_driver_locations_is_active", "is_active"),
    )
