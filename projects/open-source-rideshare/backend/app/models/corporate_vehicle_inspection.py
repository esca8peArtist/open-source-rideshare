"""Corporate Vehicle Inspection models.

Fleet managers define reusable inspection templates for company vehicles.
Drivers or fleet managers submit completed checklists (pre-trip, post-trip,
scheduled, or incident) before/after each vehicle use.  Defects discovered
during an inspection are flagged for maintenance tracking.

Models
------
CorporateVehicleInspectionTemplate — reusable checklist template per account
CorporateVehicleInspection         — a completed (or pending) inspection record

Tables
------
corporate_vehicle_inspection_templates
corporate_vehicle_inspections
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InspectionType(str, enum.Enum):
    """When/why the inspection is being performed."""

    pre_trip = "pre_trip"
    post_trip = "post_trip"
    scheduled = "scheduled"
    incident = "incident"


class InspectionStatus(str, enum.Enum):
    """Lifecycle status of a vehicle inspection."""

    pending = "pending"
    passed = "passed"
    failed = "failed"
    requires_attention = "requires_attention"


# ---------------------------------------------------------------------------
# CorporateVehicleInspectionTemplate
# ---------------------------------------------------------------------------


class CorporateVehicleInspectionTemplate(Base):
    """A reusable inspection checklist template owned by a corporate account.

    Fleet managers define the items that inspectors must check.  Templates
    can be deactivated (soft-deleted) rather than hard-deleted so that
    historical inspections can still reference them.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable template name, unique within the account.
        description: Optional longer description of the template's purpose.
        inspection_items: JSONB list of item dicts:
            [{"item_name": str, "category": str, "is_required": bool}, ...]
        is_active: Whether the template is available for new inspections.
        created_by_id: FK to users (SET NULL on delete).
        created_at: UTC creation timestamp.
        updated_at: UTC last-update timestamp.
    """

    __tablename__ = "corporate_vehicle_inspection_templates"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "name",
            name="uq_corp_veh_insp_template_account_name",
        ),
        Index("ix_corp_veh_insp_tmpl_account_id", "account_id"),
        Index("ix_corp_veh_insp_tmpl_is_active", "account_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    inspection_items: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")

    inspections: Mapped[list[CorporateVehicleInspection]] = relationship(
        "CorporateVehicleInspection",
        back_populates="template",
        lazy="raise",
    )


# ---------------------------------------------------------------------------
# CorporateVehicleInspection
# ---------------------------------------------------------------------------


class CorporateVehicleInspection(Base):
    """A completed or pending vehicle inspection record.

    Created in *pending* status when a driver or fleet manager starts an
    inspection.  Transitioned to *passed*, *failed*, or *requires_attention*
    when the inspector submits the completed checklist.

    Attributes:
        id: UUID primary key.
        template_id: FK to corporate_vehicle_inspection_templates (SET NULL).
        fleet_vehicle_id: FK to corporate_fleet_vehicles (CASCADE delete).
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        reservation_id: Optional FK to corporate_vehicle_reservations (SET NULL).
        inspection_type: Pre-trip, post-trip, scheduled, or incident.
        inspection_status: Lifecycle status; defaults to *pending*.
        inspected_by_id: FK to users (SET NULL), nullable until submitted.
        inspected_at: Timestamp when the inspection was submitted, nullable.
        odometer_miles: Vehicle odometer reading at time of inspection.
        fuel_level_pct: Fuel level as an integer percentage 0–100.
        items_checked: JSONB list of completed items:
            [{"item_name": str, "category": str, "passed": bool|None,
              "notes": str|None}, ...]
        defects_noted: JSONB list of defect description strings; set on submit.
        overall_notes: Free-text general notes from the inspector.
        maintenance_log_id: FK to corporate_vehicle_maintenance_logs (SET NULL);
            auto-populated when defects are found during submission.
        created_at: UTC creation timestamp.
        updated_at: UTC last-update timestamp.
    """

    __tablename__ = "corporate_vehicle_inspections"
    __table_args__ = (
        Index("ix_corp_veh_insp_account_id", "account_id"),
        Index("ix_corp_veh_insp_fleet_vehicle_id", "fleet_vehicle_id"),
        Index("ix_corp_veh_insp_type", "inspection_type"),
        Index("ix_corp_veh_insp_status", "inspection_status"),
        Index("ix_corp_veh_insp_inspected_at", "inspected_at"),
        Index("ix_corp_veh_insp_template_id", "template_id"),
        Index("ix_corp_veh_insp_reservation_id", "reservation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_vehicle_inspection_templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    fleet_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_vehicle_reservations.id", ondelete="SET NULL"),
        nullable=True,
    )

    inspection_type: Mapped[InspectionType] = mapped_column(
        SAEnum(InspectionType, name="inspectiontype"),
        nullable=False,
    )

    inspection_status: Mapped[InspectionStatus] = mapped_column(
        SAEnum(InspectionStatus, name="inspectionstatus"),
        nullable=False,
        default=InspectionStatus.pending,
        server_default=InspectionStatus.pending.value,
    )

    inspected_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    inspected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    odometer_miles: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fuel_level_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)

    items_checked: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    defects_noted: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    overall_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    maintenance_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_vehicle_maintenance_logs.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ---- Relationships ----

    template = relationship(
        "CorporateVehicleInspectionTemplate",
        back_populates="inspections",
        lazy="raise",
    )

    fleet_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[fleet_vehicle_id], lazy="raise"
    )

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )

    inspected_by = relationship(
        "User", foreign_keys=[inspected_by_id], lazy="raise"
    )
