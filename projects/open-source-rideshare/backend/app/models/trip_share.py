"""Trip share link model.

Riders can generate a short-lived public URL that lets anyone view
read-only ride information (driver, vehicle, status, ETA) without
logging in — the safety equivalent of "Share My Trip."
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.db.database import Base


class TripShareLink(Base):
    """A short-lived public share token for an in-progress ride."""

    __tablename__ = "trip_share_links"

    id = Column(Integer, primary_key=True)
    token = Column(String(36), unique=True, nullable=False, index=True)
    ride_id = Column(Integer, ForeignKey("rides.id"), nullable=False)
    rider_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    share_url = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
