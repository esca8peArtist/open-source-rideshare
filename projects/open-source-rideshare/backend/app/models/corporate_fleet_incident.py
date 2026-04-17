"""Corporate Fleet Incident Report models.

Fleet admins and members log and track vehicle incidents including accidents,
breakdowns, traffic violations, theft, vandalism, weather damage, and other
events. Each incident tracks type, severity, status, damage estimates, and
insurance or police reference numbers.

Models:
  CorporateFleetIncidentReport
      — one record per incident event for a corporate fleet vehicle.

Tables:
  corporate_fleet_incident_reports
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class FleetIncidentType(str, PyEnum):
    """Category of fleet vehicle incident."""

    accident = "accident"
    breakdown = "breakdown"
    traffic_violation = "traffic_violation"
    theft = "theft"
    vandalism = "vandalism"
    weather_damage = "weather_damage"
    other = "other"


class FleetIncidentSeverity(str, PyEnum):
    """Severity level of a fleet incident."""

    minor = "minor"
    moderate = "moderate"
    major = "major"
    total_loss = "total_loss"


class FleetIncidentStatus(str, PyEnum):
    """Lifecycle status of a fleet incident report."""

    reported = "reported"
    under_review = "under_review"
    resolved = "resolved"
    closed = "closed"


class CorporateFleetIncidentReport(Base):
    """A reported incident for a corporate fleet vehicle.

    Fleet members can log incidents and fleet admins can review, resolve,
    and close them. Each report captures incident type, severity, date,
    location, damage estimates, and insurance or police reference numbers.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        vehicle_id: FK to corporate_fleet_vehicles (SET NULL), nullable.
        reported_by_user_id: FK to users.id (SET NULL), nullable.
        incident_type: Category of the incident.
        severity: Severity level of the incident.
        status: Lifecycle status (reported, under_review, resolved, closed).
        incident_date: Date the incident occurred, required.
        incident_location: Location description, optional (max 500 chars).
        description: Free-text description of the incident, optional.
        damage_estimate: Estimated damage cost in USD, optional.
        insurance_claim_number: Insurance claim reference number, optional (max 100 chars).
        police_report_number: Police report reference number, optional (max 100 chars).
        third_party_involved: Whether a third party was involved, default False.
        injuries_reported: Whether injuries were reported, default False.
        resolved_at: UTC timestamp when the incident was resolved, nullable.
        resolution_notes: Free-text notes on how the incident was resolved, optional.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_fleet_incident_reports"
    __table_args__ = (
        Index("ix_fleet_incident_account_id", "account_id"),
        Index("ix_fleet_incident_vehicle_id", "vehicle_id"),
        Index("ix_fleet_incident_status", "status"),
        Index(
            "ix_fleet_incident_account_date",
            "account_id",
            "incident_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_fleet_vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )

    reported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    incident_type: Mapped[FleetIncidentType] = mapped_column(
        Enum(FleetIncidentType, name="fleetincidenttype"),
        nullable=False,
    )

    severity: Mapped[FleetIncidentSeverity] = mapped_column(
        Enum(FleetIncidentSeverity, name="fleetincidentseverity"),
        nullable=False,
    )

    status: Mapped[FleetIncidentStatus] = mapped_column(
        Enum(FleetIncidentStatus, name="fleetincidentstatus"),
        nullable=False,
        default=FleetIncidentStatus.reported,
    )

    incident_date: Mapped[date] = mapped_column(Date, nullable=False)

    incident_location: Mapped[str | None] = mapped_column(String(500), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    damage_estimate: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    insurance_claim_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    police_report_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    third_party_involved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    injuries_reported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[vehicle_id], lazy="raise"
    )

    reported_by = relationship(
        "User", foreign_keys=[reported_by_user_id], lazy="raise"
    )
