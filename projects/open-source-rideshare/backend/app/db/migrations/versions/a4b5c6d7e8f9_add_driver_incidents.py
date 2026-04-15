"""Add driver_incident_reports table for driver safety incident tracking.

Tables created:
  driver_incident_reports   — per-incident records filed by drivers

Three enum types created:
  incidenttypeenum      — passenger_harassment, physical_threat, property_damage,
                          theft, unsafe_behavior, accident, other
  incidentseverityenum  — low, medium, high, critical
  incidentstatusenum    — submitted, under_review, resolved, dismissed

Revision ID: a4b5c6d7e8f9
Revises: z1a2b3c4d5e6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None

INCIDENT_TYPE_ENUM = "incidenttypeenum"
INCIDENT_SEVERITY_ENUM = "incidentseverityenum"
INCIDENT_STATUS_ENUM = "incidentstatusenum"


def upgrade() -> None:
    incident_type_enum = sa.Enum(
        "passenger_harassment",
        "physical_threat",
        "property_damage",
        "theft",
        "unsafe_behavior",
        "accident",
        "other",
        name=INCIDENT_TYPE_ENUM,
    )
    incident_type_enum.create(op.get_bind(), checkfirst=True)

    incident_severity_enum = sa.Enum(
        "low", "medium", "high", "critical",
        name=INCIDENT_SEVERITY_ENUM,
    )
    incident_severity_enum.create(op.get_bind(), checkfirst=True)

    incident_status_enum = sa.Enum(
        "submitted", "under_review", "resolved", "dismissed",
        name=INCIDENT_STATUS_ENUM,
    )
    incident_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "driver_incident_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "incident_type",
            sa.Enum(
                "passenger_harassment",
                "physical_threat",
                "property_damage",
                "theft",
                "unsafe_behavior",
                "accident",
                "other",
                name=INCIDENT_TYPE_ENUM,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name=INCIDENT_SEVERITY_ENUM),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "submitted", "under_review", "resolved", "dismissed",
                name=INCIDENT_STATUS_ENUM,
            ),
            nullable=False,
            server_default="submitted",
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_urls", sa.String(2000), nullable=True),
        sa.Column("admin_note", sa.String(1000), nullable=True),
        sa.Column(
            "reviewed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_driver_incident_reports_driver_id",
        "driver_incident_reports",
        ["driver_id"],
    )
    op.create_index(
        "ix_driver_incident_reports_status",
        "driver_incident_reports",
        ["status"],
    )
    op.create_index(
        "ix_driver_incident_reports_severity",
        "driver_incident_reports",
        ["severity"],
    )
    op.create_index(
        "ix_driver_incident_reports_created_at",
        "driver_incident_reports",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_driver_incident_reports_created_at",
        table_name="driver_incident_reports",
    )
    op.drop_index(
        "ix_driver_incident_reports_severity",
        table_name="driver_incident_reports",
    )
    op.drop_index(
        "ix_driver_incident_reports_status",
        table_name="driver_incident_reports",
    )
    op.drop_index(
        "ix_driver_incident_reports_driver_id",
        table_name="driver_incident_reports",
    )
    op.drop_table("driver_incident_reports")

    sa.Enum(name=INCIDENT_STATUS_ENUM).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=INCIDENT_SEVERITY_ENUM).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=INCIDENT_TYPE_ENUM).drop(op.get_bind(), checkfirst=True)
