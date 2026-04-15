"""Community Safety Alert models.

Drivers and riders can report safety hazards, road conditions, and dangerous
areas — creating a community-powered safety layer.  Unlike Uber and Lyft (where
safety data is siloed and opaque), this gives every cooperative member the
ability to warn others in real time.

Alert lifecycle:
  - Non-sensitive alerts (road_hazard, construction, weather, traffic) from
    verified drivers are *auto_approved* and immediately visible.
  - Sensitive reports (dangerous_area, other) enter *pending* and require
    admin moderation before appearing to other users.
  - Any user can upvote an approved alert to signal it is still current.
  - Alerts expire automatically via `expires_at`; reporter or admin can also
    deactivate early.

Tables:
  safety_alerts        — alert definitions (reporter-managed)
  safety_alert_upvotes — per-user confirmation votes (idempotent)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enum types
# ---------------------------------------------------------------------------


class ReporterRole(str, enum.Enum):
    driver = "driver"
    rider = "rider"


class AlertType(str, enum.Enum):
    road_hazard = "road_hazard"       # pothole, debris, accident aftermath
    construction = "construction"      # active roadwork blocking lanes
    weather = "weather"                # ice, flooding, severe conditions
    traffic = "traffic"                # unusually heavy congestion
    dangerous_area = "dangerous_area"  # personal safety concern (moderated)
    other = "other"                    # catch-all (moderated)


class AlertSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ModerationStatus(str, enum.Enum):
    pending = "pending"           # awaiting admin review
    auto_approved = "auto_approved"  # low-risk type, bypassed moderation
    approved = "approved"         # admin explicitly approved
    rejected = "rejected"         # admin rejected (not shown to users)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SafetyAlert(Base):
    """A community-reported safety or hazard alert."""

    __tablename__ = "safety_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    reporter_role: Mapped[ReporterRole] = mapped_column(
        SAEnum(ReporterRole, name="reporterroleenum"), nullable=False
    )

    alert_type: Mapped[AlertType] = mapped_column(
        SAEnum(AlertType, name="alerttypeenum"), nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, name="alertseverityenum"),
        nullable=False,
        default=AlertSeverity.medium,
    )

    # Geographic point + optional influence radius.
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[float] = mapped_column(
        Float, nullable=False, default=100.0,
        comment="Approximate area affected (default 100 m)."
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle flags.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="False means deactivated by reporter or admin."
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Auto-expiry timestamp (NULL = never expires)."
    )

    # Moderation.
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        SAEnum(ModerationStatus, name="moderationstatusenum"),
        nullable=False,
        default=ModerationStatus.pending,
    )
    moderated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    moderated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    moderation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Cached upvote count — incremented on each confirmed upvote.
    upvote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    reporter = relationship("User", foreign_keys=[reporter_id])
    moderator = relationship("User", foreign_keys=[moderated_by])
    upvotes: Mapped[list["SafetyAlertUpvote"]] = relationship(
        "SafetyAlertUpvote", back_populates="alert", cascade="all, delete-orphan"
    )


class SafetyAlertUpvote(Base):
    """A user's confirmation vote that an alert is current / still relevant.

    One vote per user per alert — the unique constraint prevents duplicates.
    Upvoting is idempotent at the service layer (409 on repeat).
    """

    __tablename__ = "safety_alert_upvotes"

    __table_args__ = (
        UniqueConstraint("alert_id", "voter_id", name="uq_safety_alert_upvote"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    alert_id: Mapped[int] = mapped_column(
        ForeignKey("safety_alerts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    voter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    alert: Mapped["SafetyAlert"] = relationship("SafetyAlert", back_populates="upvotes")
    voter = relationship("User", foreign_keys=[voter_id])
