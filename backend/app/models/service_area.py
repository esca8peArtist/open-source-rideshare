from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ServiceArea(Base):
    __tablename__ = "service_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Polygon boundary — SRID 4326 (WGS84 lat/lng)
    boundary: Mapped[bytes] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326)
    )

    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
