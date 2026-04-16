"""Corporate Vehicle Incident Report models.

Fleet managers document vehicle incidents — collisions, vandalism, theft, etc. —
linking each report to the fleet vehicle and optionally to an insurance policy
for claim tracking and resolution workflow.

Models:
  CorporateVehicleIncidentReport
      — one record per incident involving a corporate fleet vehicle.

Tables:
  corporate_vehicle_incident_reports
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import Enum as PyEnum

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class IncidentType(str, PyEnum):
    """Category of corporate fleet vehicle incident."""

    collision = "collision"
    parking_damage = "parking_damage"
    vandalism = "vandalism"
    theft = "theft"
    mechanical_failure = "mechanical_failure"
    other = "other"


class IncidentStatus(str, PyEnum):
    """Workflow status of a vehicle incident report."""

    draft = "draft"
    reported = "reported"
    under_review = "under_review"
    resolved = "resolved"
    closed = "closed"


class CorporateVehicleIncidentReport(Base):
    """An incident report for a corporate fleet vehicle.

    Fleet managers create reports when a company vehicle is involved in a
    collision, parking damage, vandalism, theft, or mechanical failure.
    Reports move through a workflow: draft → reported → under_review →
    resolved → closed.  An optional insurance policy link enables claim
    number tracking.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete), not null.
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete), not null.
        incident_type: Category of the incident (IncidentType enum).
        incident_status: Current workflow status (IncidentStatus enum).
        incident_date: Calendar date the incident occurred (required).
        incident_time: Time of day the incident occurred, nullable.
        incident_location: Free-text location description, nullable.
        description: Full narrative of the incident (required).
        estimated_damage_usd: Estimated repair/replacement cost in USD, nullable.
        police_report_number: Police report reference number, nullable.
        driver_id: Integer FK to users.id (SET NULL) — driver at time of incident, nullable.
        insurance_policy_id: FK to corporate_fleet_insurance_policies (SET NULL), nullable.
        insurance_claim_number: Insurer-issued claim reference number, nullable.
        witness_info: Free-text witness names/contact details, nullable.
        reported_by_id: Integer FK to users.id (SET NULL) — user who submitted the report, nullable.
        reviewed_by_id: Integer FK to users.id (SET NULL) — admin who reviewed/resolved, nullable.
        resolved_at: UTC timestamp when the incident was resolved, nullable.
        notes: Free-text admin notes, nullable.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last updated.
    """

    __tablename__ = "corporate_vehicle_incident_reports"
    __table_args__ = (
        Index("ix_incident_account_id", "account_id"),
        Index("ix_incident_fleet_vehicle_id", "fleet_vehicle_id"),
        Index("ix_incident_status", "incident_status"),
        Index("ix_incident_date", "incident_date"),
        Index("ix_incident_insurance_policy_id", "insurance_policy_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    fleet_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )

    incident_type: Mapped[IncidentType] = mapped_column(
        Enum(IncidentType, name="incidenttype"),
        nullable=False,
    )

    incident_status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incidentstatus"),
        nullable=False,
        default=IncidentStatus.draft,
    )

    incident_date: Mapped[date] = mapped_column(Date, nullable=False)

    incident_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    incident_location: Mapped[str | None] = mapped_column(String(500), nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False)

    estimated_damage_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )

    police_report_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    insurance_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corporate_fleet_insurance_policies.id", ondelete="SET NULL"),
        nullable=True,
    )

    insurance_claim_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    witness_info: Mapped[str | None] = mapped_column(Text, nullable=True)

    reported_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    driver = relationship(
        "User", foreign_keys=[driver_id], lazy="raise"
    )

    insurance_policy = relationship(
        "CorporateFleetInsurancePolicy", foreign_keys=[insurance_policy_id], lazy="raise"
    )

    reported_by = relationship(
        "User", foreign_keys=[reported_by_id], lazy="raise"
    )

    reviewed_by = relationship(
        "User", foreign_keys=[reviewed_by_id], lazy="raise"
    )
