import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class LocationLabel(str, enum.Enum):
    HOME = "home"
    WORK = "work"
    CUSTOM = "custom"


class SavedLocation(Base):
    __tablename__ = "saved_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[LocationLabel] = mapped_column(Enum(LocationLabel), default=LocationLabel.CUSTOM)
    name: Mapped[str] = mapped_column(String(100))  # e.g. "Home", "Work", "Mom's house"
    address: Mapped[str] = mapped_column(String(500))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    place_id: Mapped[str | None] = mapped_column(String(300), nullable=True)  # Google/Mapbox place ID
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)  # optional custom icon name

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", backref="saved_locations")
