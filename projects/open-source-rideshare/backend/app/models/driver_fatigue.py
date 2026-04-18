"""Driver fatigue monitoring model.

Stores a raw event log of ride start/end events per driver.  The service
layer computes rolling active-hours from these events to enforce rest limits.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class FatigueEventType(str, enum.Enum):
    RIDE_STARTED = "RIDE_STARTED"
    RIDE_ENDED = "RIDE_ENDED"


class DriverFatigueLog(Base):
    __tablename__ = "driver_fatigue_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    ride_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[FatigueEventType] = mapped_column(
        Enum(FatigueEventType), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
