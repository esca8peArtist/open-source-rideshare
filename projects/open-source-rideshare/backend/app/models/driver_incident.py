"""Driver incident report model.

Drivers can report incidents involving passengers — harassment, threats,
property damage, theft, accidents, or other unsafe behavior.  Platform
admins review and resolve each report.

As a cooperative we take driver safety seriously and provide a transparent
audit trail for every incident — unlike Uber/Lyft where driver complaints
often disappear into a support ticket void.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class IncidentType(str, enum.Enum):
    passenger_harassment = "passenger_harassment"
    physical_threat = "physical_threat"
    property_damage = "property_damage"
    theft = "theft"
    unsafe_behavior = "unsafe_behavior"
    accident = "accident"
    other = "other"


class IncidentSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IncidentStatus(str, enum.Enum):
    submitted = "submitted"
    under_review = "under_review"
    resolved = "resolved"
    dismissed = "dismissed"


class DriverIncidentReport(Base):
    """A safety incident reported by a driver.

    Evidence is stored as a comma-separated list of URL strings in
    *evidence_urls* (kept simple to avoid a JSON column dependency across
    DB dialects).  In production these would be signed object-storage URLs.
    """

    __tablename__ = "driver_incident_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # The ride during which the incident occurred (nullable — incidents may
    # be reported after the ride or in a non-ride context)
    ride_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("rides.id", ondelete="SET NULL"), nullable=True
    )

    incident_type: Mapped[str] = mapped_column(
        Enum(
            "passenger_harassment",
            "physical_threat",
            "property_damage",
            "theft",
            "unsafe_behavior",
            "accident",
            "other",
            name="incidenttypeenum",
        ),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        Enum(
            "low",
            "medium",
            "high",
            "critical",
            name="incidentseverityenum",
        ),
        nullable=False,
        server_default="medium",
    )

    status: Mapped[str] = mapped_column(
        Enum(
            "submitted",
            "under_review",
            "resolved",
            "dismissed",
            name="incidentstatusenum",
        ),
        nullable=False,
        server_default="submitted",
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Comma-separated evidence URL list (kept as plain string for dialect portability)
    evidence_urls: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Admin resolution fields
    admin_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_driver_incident_reports_driver_id", "driver_id"),
        Index("ix_driver_incident_reports_status", "status"),
        Index("ix_driver_incident_reports_severity", "severity"),
        Index("ix_driver_incident_reports_created_at", "created_at"),
    )
