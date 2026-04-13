import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class SOSStatus(str, enum.Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


class SOSAlert(Base):
    __tablename__ = "sos_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ride_id: Mapped[int | None] = mapped_column(ForeignKey("rides.id"), nullable=True, index=True)
    status: Mapped[SOSStatus] = mapped_column(Enum(SOSStatus), default=SOSStatus.ACTIVE)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    ride = relationship("Ride", foreign_keys=[ride_id])
    resolver = relationship("User", foreign_keys=[resolved_by])


class TripShareToken(Base):
    __tablename__ = "trip_share_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ride = relationship("Ride", foreign_keys=[ride_id])
    creator = relationship("User", foreign_keys=[created_by])


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))
    relationship_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])
